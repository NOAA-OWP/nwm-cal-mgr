"""
This module contains methods to read and save formulation configurations.

@author: Nels Frazer, Xia Feng
"""

import json
from datetime import datetime
from enum import Enum

json.encoder.FLOAT_REPR = str  # lambda x: format(x, '%.09f')
import logging

logging.disable(logging.DEBUG)
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Annotated, Any, Dict, Mapping, Optional, Sequence, Union, List, Set

try:  # to get literal in python 3.7, it was added to typing in 3.8
    from typing import Literal
except ImportError:
    from typing_extensions import Literal

import geopandas as gpd
import pandas as pd
from config.multi import MultiBMI
from config.realization import CatchmentRealization, NgenRealization, Realization
from hypy.hydrolocation import NWISLocation  # type: ignore
from hypy.nexus import Nexus  # type: ignore
from pydantic import BaseModel, ConfigDict, Field, FilePath, model_validator

from .calibration_cathment import AdjustableCatchment, CalibrationCatchment
from .calibration_set import CalibrationSet, UniformCalibrationSet
from .model import Configurable, ModelExec, PosInt
from .parameter import Parameter, Parameters


class NgenStrategy(str, Enum):
    """ """

    # multiplier = "multiplier"
    uniform = "uniform"
    explicit = "explicit"
    independent = "independent"
    grouped = "grouped"


def _params_as_df(params: Mapping[str, Parameters], name: str = None):
    if not params or len(params) == 0:
        raise ValueError("The 'params' mapping cannot be empty.")

    if not name:
        dfs = []
        for k, v in params.items():
            df = pd.DataFrame([s.__dict__ for s in v])
            df["model"] = k
            df.rename(columns={"name": "param"}, inplace=True)
            dfs.append(df)
        dfs = pd.concat(dfs)
        dfs["fac"] = dfs["param"].factorize()[0]
        return dfs
    else:
        p = params.get(name, [])
        df = pd.DataFrame([s.__dict__ for s in p])
        df["model"] = name
        df.rename(columns={"name": "param"}, inplace=True)
        df["fac"] = df["param"].factorize()[0]
        return df


def _map_params_to_realization(
    params: Mapping[str, Parameters], realization: Any, group_name: str = None
):
    # Map params to global realization
    if hasattr(realization, "formulations"):
        module = realization.formulations[0].params

        if isinstance(module, MultiBMI):
            dfs = []
            for m in module.modules:
                dfs.append(_params_as_df(params, m.params.model_name))
            return pd.concat(dfs)
        else:
            return _params_as_df(params, module.model_name)

    # Map params to grouped realization
    elif hasattr(realization, "formulation_groups"):
        if group_name is None:
            raise ValueError("Must provide 'group_name' for grouped realization parameter mapping")

        group_formulations = realization.formulation_groups[group_name]
        dfs = []

        for formulation in group_formulations:
            module = formulation.params
            if isinstance(module, MultiBMI):
                for m in module.modules:
                    model_name = m.params.model_name
                    # Only process if model is in calibratable params
                    if model_name in params:
                        dfs.append(_params_as_df(params, m.params.model_name))
            else:
                model_name = module.model_name
                if model_name in params:
                    dfs.append(_params_as_df(params, module.model_name))

        if dfs:
            return pd.concat(dfs)
        else:
            return pd.DataFrame()


class NgenBase(ModelExec):
    """
    Data class specific for Ngen

    Inherits the ModelParams attributes and Configurable interface
    """

    type: Literal["ngen"]
    # required fields
    # TODO with the ability to generate realizations programaticaly, this may not be
    # strictly required any longer...for now it "works" so we are using info from
    # an existing realization to build various calibration realization configs
    # but we should probably take a closer look at this in the near future
    realization: FilePath
    catchments: FilePath
    nexus: FilePath
    crosswalk: FilePath
    ngen_realization: Optional[NgenRealization] = None
    routing_output: Optional[Path] = Field(default=Path("flowveldepth_Ngen.h5"))
    # optional fields
    partitions: Optional[FilePath] = None
    parallel: Optional[PosInt] = None
    params: Optional[Mapping[str, Parameters]] = None
    # dependent fields
    binary: str = "ngen"
    args: Optional[str] = None
    obsflow: Optional[FilePath] = None
    nwmflow: Optional[FilePath] = None

    # private, not validated
    _catchments: Sequence["CalibrationCatchment"] = []
    _catchment_hydro_fabric: gpd.GeoDataFrame
    _flowpath_hydro_fabric: gpd.GeoDataFrame
    _nexus_hydro_fabric: gpd.GeoDataFrame
    _x_walk: pd.Series
    _precip: gpd.GeoDataFrame
    _wb_lst: list

    class Config:
        """Override configuration for pydantic BaseModel"""

        # underscore_attrs_are_private = True
        use_enum_values = True
        # smart_union = True

    def __init__(self, **kwargs):
        # Let pydantic work its magic
        super().__init__(**kwargs)
        # Ensure the realization file exists before copying
        if not self.realization.exists():
            raise FileNotFoundError(
                f"Realization file '{self.realization}' does not exist."
            )

        # Make a copy of the config file, just in case
        shutil.copy(self.realization, str(self.realization) + "_original")

        # Reading catchments, flowpaths, and nexus
        try:
            self._catchment_hydro_fabric = gpd.read_file(
                self.catchments, layer="divides"
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to read catchment hydro fabric from {self.catchments}: {e}"
            )

        self._catchment_hydro_fabric.set_index("div_id", inplace=True)

        try:
            self._flowpath_hydro_fabric = gpd.read_file(
                self.catchments, layer="flowpaths"
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to read flowpath hydro fabric from {self.catchments}: {e}"
            )

        self._flowpath_hydro_fabric.set_index("div_id", inplace=True)

        try:
            self._nexus_hydro_fabric = gpd.read_file(self.nexus, layer="nexus")
        except Exception as e:
            raise RuntimeError(
                f"Failed to read nexus hydro fabric from {self.nexus}: {e}"
            )

        self._nexus_hydro_fabric.set_index("nex_id", inplace=True)

        # Handle crosswalk file
        self._x_walk = pd.Series(dtype=object)
        try:
            with open(self.crosswalk) as fp:
                data = json.load(fp)
                for id, values in data.items():
                    gage = values.get("Gage_no")
                    if gage:
                        if not isinstance(gage, str):
                            gage = gage[0]
                        if gage != "":
                            # Convert ids to integers to match NHF format
                            try:
                                self._x_walk[int(id)] = gage
                            except ValueError:
                                raise ValueError(
                                    f"Crosswalk contains non-integer nexus ID: '{id}'"
                                )
        except FileNotFoundError:
            raise FileNotFoundError(f"Crosswalk file '{self.crosswalk}' not found.")
        except json.JSONDecodeError:
            raise ValueError(
                f"Failed to parse JSON from crosswalk file '{self.crosswalk}'."
            )

        # Read the calibration specific info
        with open(self.realization) as fp:
            data = json.load(fp)
        self.ngen_realization = NgenRealization(**data)

    @property
    def config_file(self) -> Path:
        """Path to the configuration file for this calibration

        Returns:
            Path: to ngen realization configuration file
        """
        return self.realization

    @property
    def adjustables(self) -> Sequence["CalibrationCatchment"]:
        """A list of Catchments for calibration

        These catchments hold information about the parameters/calibration data for that catchment

        Returns:
            Sequence[CalibrationCatchment]: A list like container of CalibrationCatchment objects
        """
        return self._catchments

    @model_validator(mode="before")
    def set_defaults(cls, values: Dict):
        """Compose default values

            This validator will set/adjust the following data values for the class
            args: if not explicitly configured, ngen args default to
                  catchments "all" nexus "all" realization
            binary: if parallel is defined and valid then the binary command is adjusted to
                    mpirun -n parallel binary
                    also, if parallel is defined the args are adjusted to include the partition field
                    catchments "" nexus "" realization partitions
        Args:
            values (dict): mapping of key/value pairs to validate

        Returns:
            Dict: validated key/value pairs with default values set for known keys
        """
        parallel = values.get("parallel")
        partitions = values.get("partitions")
        binary = values.get("binary")
        args = values.get("args")
        catchments = values.get("catchments")
        nexus = values.get("nexus")
        realization = values.get("realization")

        custom_args = False
        if args is None:
            # args = '{} "" {} "" {}'.format(catchments.resolve(), nexus.resolve(), realization.name)
            args = '{} "all" {} "all" {}'.format(
                Path(catchments).resolve(),
                Path(nexus).resolve(),
                Path(realization).name
            )
            values["args"] = args
        else:
            custom_args = True

        if parallel is not None and partitions is not None:
            # Don't prefix the mpirun command if it already exists.
            # This prevent inserting redundant mpirun command in situations
            # such as cloning a Ngen object from another Ngen object
            if not binary.startswith("mpirun -n"):
                binary = f"mpirun -n {parallel} --bind-to none {binary}"
            if not custom_args:
                # only append this if args weren't already custom defined by user
                args += f" {partitions}"
            values["binary"] = binary
            values["args"] = args

        return values

    @model_validator(
        mode="before"
    )  # pre-check, don't validate anything else if this fails
    def check_for_partitions(cls, values: dict):
        """Validate that if parallel is used and valid that partitions is passed (and valid)

        Args:
            values (dict): values to validate

        Raises:
            ValueError: If no partition field is defined and parallel support (greater than 1) is requested.

        Returns:
            dict: Values valid for this rule
        """
        parallel = values.get("parallel")
        partitions = values.get("partitions")
        if parallel is not None and parallel > 1 and partitions is None:
            raise ValueError("Must provide partitions if using parallel")
        return values

    def update_config(
        self, i: int, params: "pd.DataFrame", id: str = None, **kwargs
    ):
        """_summary_

        Args:
            i (int): _description_
            params (pd.DataFrame): _description_
            id (str): _description_
            **kwargs: Additional arguments
        """
        if id is None:
            if hasattr(self.ngen_realization, 'formulation_groups') and self.ngen_realization.formulation_groups:
                # Update grouped realization
                for grp_name in self.ngen_realization.formulation_groups.keys():
                    formulation_configs = self.ngen_realization.formulation_groups[grp_name]
                    if not formulation_configs or len(formulation_configs) == 0:
                        raise ValueError(f"No formulation configuration found for group '{grp_name}'")
                    module = formulation_configs[0].params
                    self.apply_params_to_module(i, params, module)
            else:
                # Update global config
                module = self.ngen_realization.global_config.formulations[0].params
                self.apply_params_to_module(i, params, module)
        else:  # update specific catchment or formulation group
            if hasattr(self.ngen_realization, 'catchments') and id in self.ngen_realization.catchments:
                module = self.ngen_realization.catchments[id].formulations[0].params
            elif hasattr(self.ngen_realization, 'formulation_groups'):
                formulation_configs = self.ngen_realization.formulation_groups[id]
                if not formulation_configs or len(formulation_configs) == 0:
                    raise ValueError(f"No formulation configuration found for '{id}'")
                module = formulation_configs[0].params
            else:
                raise ValueError(f"Could not find configuration for id: {id}")

            # Apply params to module
            self.apply_params_to_module(i, params, module)

    def apply_params_to_module(self, i: Union[int, str], params: "pd.DataFrame", module) -> None:
        """Apply updated parameters to a module"""

        if hasattr(module, "modules"):
            modules = [m.params.model_name for m in module.modules]
        else:
            modules = [module.model_name]

        params0 = params.copy(deep=1)
        # CFE is present, copy shared CFE params to SFT and SMP
        if ("SMP" in modules or "SFT" in modules) and "CFE" in modules:
            for m1 in ["SMP", "SFT"]:
                if m1 not in modules:
                    continue
                for p1 in ["b", "maxsmc", "satpsi"]:
                    par1 = params0.loc[
                        (params0["model"] == "CFE") & (params0["param"] == p1)
                    ]
                    if len(par1) == 1:
                        par2 = par1.copy(deep=1)
                        par2["model"] = m1
                        if p1 == "maxsmc":
                            par2["param"] = "smcmax"
                        params = pd.concat([params, par2])

        # SFT is calibrated without CFE copy SFT params to SMP
        elif "SMP" in modules and "SFT" in modules and "CFE" not in modules:
            for p1 in ["b", "smcmax", "satpsi"]:  # This assumes the SFT parameter is supplied as smcmax, not as maxsmc to match CFE
                par1 = params0.loc[
                    (params0["model"] == "SFT") & (params0["param"] == p1)
                ]
                if len(par1):
                    par2 = par1.copy(deep=1)
                    par2["model"] = "SMP"
                    params = pd.concat([params, par2])

        groups = params.set_index("param").groupby("model")
        if isinstance(module, MultiBMI):
            for m in module.modules:
                name = m.params.model_name
                if name in groups.groups:
                    p = groups.get_group(name)
                    m.params.model_params = p[str(i)].to_dict()
        else:
            if module.model_name in groups.groups:
                p = groups.get_group(module.model_name)
                module.model_params = p[str(i)].to_dict()

    def write_realization_file(self, path: Path = Path("./")) -> None:
        """
        Write the current ngen_realization to realization file.
        Separate realization writing function allows grouped parameters to be updated in sequence
        and then written out after all updates are complete.

        Args:
            path: Path to realization file output
        """
        def safe_model_dump_json(
            model: BaseModel, *, by_alias=True, exclude_none=True, indent=4
        ) -> str:
            """
            Serialize a Pydantic v2 model to JSON safely, including nested models and arbitrary objects.
            """

            def convert(obj):
                # Handle Pydantic models
                if isinstance(obj, BaseModel):
                    data = {}
                    for k, v in obj.__dict__.items():
                        if exclude_none and v is None:
                            continue
                        # Skip empty dicts and lists, except output_vars
                        if k != "output_vars":
                            if isinstance(v, dict) and len(v) == 0:
                                continue
                            if isinstance(v, list) and len(v) == 0:
                                continue
                        # Use alias if requested
                        field = obj.model_fields.get(k)
                        key = field.alias if by_alias and field and field.alias else k
                        data[key] = convert(v)
                    return data
                # Handle dicts
                elif isinstance(obj, dict):
                    result = {}
                    for k, v in obj.items():
                        if exclude_none and v is None:
                            continue
                        # Skip empty dicts and lists
                        if isinstance(v, dict) and len(v) == 0:
                            continue
                        if isinstance(v, list) and len(v) == 0:
                            continue
                        result[k] = convert(v)
                    return result
                # Handle lists, tuples, sets
                elif isinstance(obj, (list, tuple, set)):
                    return [convert(v) for v in obj]
                # Handle objects that can't be serialized
                else:
                    try:
                        json.dumps(obj)
                        return obj
                    except TypeError:
                        if isinstance(obj, type):
                            return f"{obj.__module__}.{obj.__qualname__}"
                        return str(obj)  # fallback to string

            safe_dict = convert(model)
            return json.dumps(safe_dict, indent=indent)

        # if path does not exist, issue an error (since the path should have been created prior to this call)
        if not path.exists():
            msg = f"Path '{path}' does not exist to save the realization file"
            logging.error(msg)
            raise FileNotFoundError(msg)

        with open(path / self.realization.name, "w") as fp:
            fp.write(
                safe_model_dump_json(
                    self.ngen_realization, by_alias=True, exclude_none=True, indent=4
                )
            )


class NgenExplicit(NgenBase):
    strategy: Literal[NgenStrategy.explicit]

    def __init__(self, **kwargs):
        # Let pydantic work its magic
        super().__init__(**kwargs)
        # now we work ours
        start_t = self.ngen_realization.time.start_time
        end_t = self.ngen_realization.time.end_time
        # Setup each calibration catchment
        for id, catchment in self.ngen_realization.catchments.items():
            if hasattr(catchment, "calibration"):
                try:
                    fabric = self._catchment_hydro_fabric.loc[id]
                except KeyError:
                    continue
                try:
                    nwis = self._x_walk[id]
                except KeyError:
                    raise (
                        RuntimeError(
                            "Cannot establish mapping of catchment {} to nwis location in cross walk".format(
                                id
                            )
                        )
                    )
                try:
                    dn_nexus_id = self._flowpath_hydro_fabric.loc[id]["dn_nex_id"]
                    nexus_data = self._nexus_hydro_fabric.loc[dn_nexus_id]
                except KeyError:
                    raise (
                        RuntimeError(
                            "No suitable nexus found for catchment {}".format(id)
                        )
                    )

                # establish the hydro location for the observation nexus associated with this catchment
                location = NWISLocation(nwis, nexus_data.name, nexus_data.geometry)
                nexus = Nexus(nexus_data.name, location, (), id)
                output_var = catchment.formulations[0].params.main_output_variable
                # read params from the realization calibration definition
                params = {
                    model: [Parameter(**p) for p in params]
                    for model, params in catchment.calibration.items()
                }
                params = _map_params_to_realization(params, catchment)
                # TODO define these extra params in the realization config and parse them out explicity per catchment, cause why not?
                eval_params = self.eval_params.model_copy()
                eval_params.id = id
                self._catchments.append(
                    CalibrationCatchment(
                        self.workdir,
                        id,
                        nexus,
                        start_t,
                        end_t,
                        fabric,
                        output_var,
                        eval_params,
                        params,
                    )
                )

    def update_config(self, i: int, params: "pd.DataFrame", id: str, **kwargs):
        """_summary_

        Args:
            i (int): _description_
            params (pd.DataFrame): _description_
            id (str): _description_
        """

        if id is None:
            raise RuntimeError(
                "NgenExplicit calibration must recieve an id to update, not None"
            )

        super().update_config(i, params, id, **kwargs)


class NgenIndependent(NgenBase):
    # TODO Error if not routing block in ngen_realization
    strategy: Literal[NgenStrategy.independent]
    params: Mapping[str, Parameters]  # required in this case...

    def __init__(self, **kwargs):
        # Let pydantic work its magic
        super().__init__(**kwargs)
        # FIXME cannot strip all global params cause things like sloth depend on them
        # but the global params may have defaults in place that are not the same as the requested
        # calibration params.  This shouldn't be an issue since each catchment overrides the global config
        # and it won't actually be used, but the global config definition may not be correct.
        # self._strip_global_params()
        # now we work ours
        start_t = self.ngen_realization.time.start_time
        end_t = self.ngen_realization.time.end_time
        # Setup each calibration catchment
        catchments = []
        eval_nexus = []
        catchment_realizations = {}
        g_conf = self.ngen_realization.global_config.model_copy(deep=True).model_dump(by_alias=True)
        for id in self._catchment_hydro_fabric.index:
            # Copy the global configuration into each catchment
            catchment_realizations[id] = CatchmentRealization(**g_conf)
            # Need to fix the forcing definition or ngen will not work
            # for individual catchment configs, it doesn't apply pattern resolution
            # and will read the directory `path` key as the file key and will segfault
            pattern = catchment_realizations[id].forcing.file_pattern
            path = catchment_realizations[id].forcing.path
            catchment_realizations[id].forcing.file_pattern = None
            pattern = pattern.replace("{{id}}", id)
            pattern = re.compile(pattern.replace("{{ID}}", id))
            for f in path.iterdir():
                if pattern.match(f.name):
                    catchment_realizations[id].forcing.path = f.resolve()

        self.ngen_realization.catchments = catchment_realizations

        for (
            id,
            catchment,
        ) in self.ngen_realization.catchments.items():  # data['catchments'].items():
            try:
                dn_nexus_id = self._flowpath_hydro_fabric.loc[id]["dn_nex_id"]
                nexus_data = self._nexus_hydro_fabric.loc[dn_nexus_id]
            except KeyError:
                raise (
                    RuntimeError("No suitable nexus found for catchment {}".format(id))
                )
            nwis = None
            try:
                nwis = self._x_walk.loc[id]
            except KeyError:
                nwis = None
            if nwis is not None:
                # establish the hydro location for the observation nexus associated with this catchment
                location = NWISLocation(nwis, nexus_data.name, nexus_data.geometry)
                nexus = Nexus(nexus_data.name, location, (), id)
                eval_nexus.append(nexus)  # FIXME why did I make this a tuple???
            else:
                # in this case, we don't care if all nexus are observable, just need one downstream
                # FIXME use the graph to work backwards from an observable nexus to all upstream catchments
                # and create independent "sets"
                nexus = Nexus(nexus_data.name, None, (), id)
            # FIXME pick up params per catchmment somehow???
            params = _map_params_to_realization(self.params, catchment)
            catchments.append(AdjustableCatchment(self.workdir, id, nexus, params))

        if len(eval_nexus) != 1:
            raise RuntimeError(
                "Currently only a single nexus in the hydrfabric can be gaged"
            )
        self._catchments.append(
            CalibrationSet(
                catchments,
                eval_nexus[0],
                self.routing_output,
                start_t,
                end_t,
                self.eval_params,
            )
        )

    def _strip_global_params(self) -> None:
        module = self.ngen_realization.global_config.formulations[0].params
        if isinstance(module, MultiBMI):
            for m in module.modules:
                m.params.model_params = None
        else:
            module.model_params = None


class NgenUniform(NgenBase):
    """
    Uses a global ngen configuration and permutes just this global parameter space
    which is applied to each catchment in the hydrofabric being simulated.
    """

    # TODO Error if not routing block in ngen_realization
    strategy: Literal[NgenStrategy.uniform]
    params: Mapping[str, Parameters]  # required in this case...

    def __init__(self, **kwargs):
        # Let pydantic work its magic
        super().__init__(**kwargs)

        # Check if params is provided and non-empty
        if not self.params or len(self.params) == 0:
            raise ValueError(
                "NgenUniform requires non-empty 'params' for configuration."
            )

        # now we work ours
        start_t = self.ngen_realization.time.start_time
        end_t = self.ngen_realization.time.end_time
        eval_nexus = []

        for catchment_id in self._catchment_hydro_fabric.index:
            try:
                dn_nexus_id = self._flowpath_hydro_fabric.loc[catchment_id]["dn_nex_id"]
                nexus_data = self._nexus_hydro_fabric.loc[dn_nexus_id]
            except KeyError:
                continue
            # look for an observable nexus
            nwis = None
            try:
                nwis = self._x_walk.loc[catchment_id]
            except KeyError:
                # not an observable nexus, try the next one
                continue
            # establish the hydro location for the observation nexus associated with this catchment
            location = NWISLocation(nwis, nexus_data.name, nexus_data.geometry)
            nexus = Nexus(nexus_data.name, location, (), id)
            eval_nexus.append(nexus)
        if len(eval_nexus) != 1:
            raise RuntimeError(
                "Currently only a single nexus in the hydrfabric can be gaged"
            )
        params = _params_as_df(self.params)

        # Identify rivers draining to the stream gage
        self.routing_output = "troute_output_" + start_t.strftime("%Y%m%d%H%M") + ".nc"
        nexus_id = eval_nexus[0].id

        self._wb_lst = [
            str(x) for x in list(
                self._flowpath_hydro_fabric.query("dn_nex_id==@nexus_id").index
            )
        ]
        self._catchments.append(
            UniformCalibrationSet(
                eval_nexus=eval_nexus[0],
                routing_output=self.routing_output,
                start_time=start_t,
                end_time=end_t,
                eval_params=self.eval_params,
                obsflow_file=self.obsflow,
                nwmflow_file=self.nwmflow,
                params=params,
                wb_lst=self._wb_lst,
            )
        )


class NgenGrouped(NgenBase):
    """
    Uses a grouped ngen configuration and permutes parameter values within each formulation
    """

    strategy: Literal[NgenStrategy.grouped]
    formulation_groups: Dict[str, List[str]] = {}
    grp_to_cat: Dict[str, List[str]] = {}
    grp_params_map: Dict[str, Any] = {}
    cat_to_grp: Dict[str, str] = {}
    grp_models: Dict[str, Set[str]] = {}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Extract formulation groups from realization file
        self._extract_formulation_groups()

        # Validate formulation groups and map parameters to groups
        self._map_group_params()

        # Create calibration sets for groups
        self._build_grouped_cal_sets()

    def _extract_formulation_groups(self) -> None:
        """
        Extract formulation groups from realization file and map catchments to formulation groups
        """
        if not hasattr(self.ngen_realization, 'formulation_groups'):
            raise ValueError(
                "Realization file must contain 'formulation_groups' section for grouped strategy"
            )

        if not hasattr(self.ngen_realization, 'catchments'):
            raise ValueError(
                "Realization file must contain 'catchments' section for grouped strategy"
            )

        # Retrieve formulations for each group
        for grp_name in self.ngen_realization.formulation_groups.keys():
            self.formulation_groups[grp_name] = self.ngen_realization.formulation_groups[grp_name]

        # Build catchment-to-group mapping
        for catchment_id, catchment_config in self.ngen_realization.catchments.items():
            if hasattr(catchment_config, 'formulations'):
                grp_name = catchment_config.formulations
                if grp_name not in self.formulation_groups:
                    raise ValueError(
                        f"Catchment '{catchment_id}' references unknown formulation group '{grp_name}'"
                    )
                self.cat_to_grp[catchment_id] = grp_name

        # Retrieve models used in each group
        for grp_name, grp_config in self.formulation_groups.items():
            model_names = set()
            for config in grp_config:
                # Retrieve module param section of group formulation
                module_param = config.params
                for mod in module_param.modules:
                    model_name = mod.params.model_name
                    model_names.add(model_name)
            self.grp_models[grp_name] = model_names

    def _get_params_for_grp(self, grp_name: str) -> Dict[str, List[Parameter]]:
        """"
        Retrieve parameters for a specific formulation group
        """

        # Retrieve modules for a given group that are calibratable
        cal_models = (self.grp_models.get(grp_name, set()) & set(self.params.keys()))

        # Filter parameters to calibratable models in group
        params_for_grp = {}
        for model_name in cal_models:
            if model_name in self.params:
                params_for_grp[model_name] = self.params[model_name]
        return params_for_grp

    def _map_group_params(self) -> None:
        """
        Validate group formulations and create group parameter mappings
        """

        for grp_name in self.formulation_groups.keys():

            # Retrieve catchments for formulation group
            cat_in_grp = [cat_id for cat_id, grp in self.cat_to_grp.items() if grp == grp_name]
            self.grp_to_cat[grp_name] = cat_in_grp

            # Retrieve parameters for formulation group
            params_for_grp = self._get_params_for_grp(grp_name)
            params_dict = {model: params for model, params in params_for_grp.items()}

            # Map params to realization format
            params_df = _map_params_to_realization(params_dict, self.ngen_realization, grp_name)
            params_df.reset_index(drop=True, inplace=True)
            params_df["fac"] = range(len(params_df))
            self.grp_params_map[grp_name] = params_df

    def _find_basin_gage_nexus(self) -> Optional[tuple]:
        """
        Find the single gage nexus for the basin
        """

        # Search for gage in the crosswalk
        for id_key, nwis in self._x_walk.items():
            if not nwis and nwis == "":
                continue

            # Check if catchment id exists
            cat_id = id_key
            if id_key not in self._catchment_hydro_fabric.index:
                continue

            # Map catchment to nexus
            try:
                dn_nexus_id = self._flowpath_hydro_fabric.loc[cat_id]["dn_nex_id"]
                nexus_data = self._nexus_hydro_fabric.loc[dn_nexus_id]
                location = NWISLocation(nwis, nexus_data.name, nexus_data.geometry)
                nexus = Nexus(nexus_data.name, location, (), cat_id)
                return (nexus, nwis)
            except KeyError as e:
                print(f"Could not map catchment {cat_id} to nexus: {e}")
                continue

    def _build_grouped_cal_sets(self) -> None:
        """
        Create calibration parameter sets for each formulation group
        """
        start_t = self.ngen_realization.time.start_time
        end_t = self.ngen_realization.time.end_time

        # Find single basin gage nexus for all groups
        basin_gage = self._find_basin_gage_nexus()
        if not basin_gage:
            raise RuntimeError(
                "No gage found in crosswalk for evaluation"
            )
        eval_nexus, nwis_id = basin_gage

        # Generate timestamped routing output file
        self.routing_output = "troute_output_" + start_t.strftime("%Y%m%d%H%M") + ".nc"

        # Identify rivers draining to the stream gage
        self._wb_lst = []
        try:
            # Get catchments draining to nexus
            gage_nexus_id = eval_nexus.id
            self._wb_lst = [
                str(x) for x in list(
                    self._flowpath_hydro_fabric.query("dn_nex_id==@gage_nexus_id").index
                )
            ]
        except (KeyError, Exception) as e:
            # Include all catchments in wb_lst as fallback
            self._wb_lst = [str(x) for x in list(self._catchment_hydro_fabric.index)]
            print(f"Could not identify downstream catchments for nexus: {e}")

        # Construct calibration set for group
        for grp_name, grp_catchments in self.grp_to_cat.items():
            grp_params = self.grp_params_map[grp_name]
            adjustables = []

            # Process nexus/adjustable object for each catchment
            for cat_id in grp_catchments:
                try:
                    dn_nexus_id = self._flowpath_hydro_fabric.loc[int(cat_id)]["dn_nex_id"]
                    nexus_data = self._nexus_hydro_fabric.loc[dn_nexus_id]
                except KeyError:
                    raise RuntimeError(f"No nexus found for catchment {cat_id}")

                # Create adjustable catchment object
                nexus = Nexus(nexus_data.name, None, cat_id)
                adjustables.append(
                    AdjustableCatchment(
                        self.workdir,
                        grp_name,
                        nexus,
                        grp_params
                    )
                )

            # Create calibration set for each group
            grp_eval_params = self.eval_params.model_copy()
            grp_eval_params.id = grp_name

            self._catchments.append(
                CalibrationSet(
                    adjustables=adjustables,
                    eval_nexus=eval_nexus,
                    routing_output=self.routing_output,
                    start_time=start_t,
                    end_time=end_t,
                    eval_params=grp_eval_params,
                    obsflow_file=self.obsflow,
                    nwmflow_file=self.nwmflow,
                    wb_lst=self._wb_lst,
                )
            )


class Ngen(BaseModel, Configurable):
    model_config = ConfigDict()

    type: Literal["ngen"]

    strategy: Annotated[
        Union[NgenExplicit, NgenIndependent, NgenUniform, NgenGrouped],
        Field(discriminator="strategy"),
    ]

    @model_validator(mode="before")
    def convert_strategy_string(cls, values: dict[str, Any]) -> dict[str, Any]:
        """
        Convert the 'strategy' string in the YAML into the correct Ngen subclass
        before Pydantic validation.
        """
        strat = values.get("strategy")
        if isinstance(strat, str):
            if strat == "uniform":
                values["strategy"] = NgenUniform(**values)
            elif strat == "explicit":
                values["strategy"] = NgenExplicit(**values)
            elif strat == "independent":
                values["strategy"] = NgenIndependent(**values)
            elif strat == "grouped":
                values["strategy"] = NgenGrouped(**values)
            else:
                raise ValueError(f"Unknown strategy '{strat}'")
        return values

    # proxy methods for Configurable
    def get_args(self) -> str:
        return self.strategy.get_args()

    def get_binary(self) -> str:
        return self.strategy.get_binary()

    def update_config(self, *args, **kwargs):
        return self.strategy.update_config(*args, **kwargs)

    # proxy methods for model
    @property
    def adjustables(self):
        return self.strategy._catchments

    @property
    def model_strategy(self):
        return self.strategy.strategy

    def restart(self) -> int:
        starts = []
        for catchment in self.adjustables:
            starts.append(catchment.restart())
        if all(x == starts[0] for x in starts):
            # if everyone agress on the iteration...
            return starts[0]
        else:
            return 0

    @property
    def model_type(self):
        return self.strategy.type

    def resolve_paths(self):
        """resolve any possible relative paths in the realization"""
        if self.strategy.ngen_realization is not None:
            self.strategy.ngen_realization.resolve_paths()

    @property
    def best_params(self):
        return self.strategy.eval_params.best_params

    @property
    def model_params(self):
        return self.strategy.params

    @property
    def realization_file(self):
        return self.strategy.realization
