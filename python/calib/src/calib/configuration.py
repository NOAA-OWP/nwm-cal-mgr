"""
This module implements several classes to hold generation confugrations.

@author: Nels Frazer, Xia Feng
"""

from __future__ import annotations  # for pydnaitc

import os
from pathlib import Path
from typing import Annotated, Dict, List, Optional, Union

try:  # to get literal in python 3.7, it was added to typing in 3.8
    from typing import Literal
except ImportError:
    from typing_extensions import Literal

import json
import shutil
import traceback
from datetime import datetime
from pathlib import Path

import ewts
import geopandas as gpd
import netCDF4
import pandas as pd
from common import get_calmgr_logger
from pydantic import BaseModel, DirectoryPath, Field, PrivateAttr

from .model import ModelExec, PosInt
from .ngen import Ngen
from .strategy import Estimation, Sensitivity

logger = get_calmgr_logger()


class General(BaseModel):
    """General configuration class."""

    # Required fields
    strategy: Union[Estimation, Sensitivity] = Field(discriminator="type")
    iterations: int
    # Fields with reasonable defaults
    restart: bool = False
    start_iteration: PosInt = 0
    workdir: DirectoryPath = Path("./")
    name: str
    yaml_file: Path
    # Optional fields
    log: Optional[bool] = False
    parameter_log_file: Optional[Path] = None
    objective_log_file: Optional[Path] = None
    random_seed: Optional[int] = None
    calibration_run_id: Optional[int] = None
    ngen_cerf: Optional[bool] = None
    auth_token: Optional[str] = None
    ngencerf_base_url: Optional[str] = None
    # Private
    _calib_path: Path
    _valid_path: Path

    class Config:
        """Override configuration for pydantic BaseModel."""

        # underscore_attrs_are_private = True
        use_enum_values = True
        # smart_union = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._calib_path = os.path.join(
            str(self.workdir) + "/Output", "Calibration_Run"
        )
        self._valid_path = os.path.join(str(self.workdir) + "/Output", "Validation_Run")
        try:
            os.makedirs(self._calib_path, exist_ok=True)
            os.makedirs(self._valid_path, exist_ok=True)
        except OSError as error:
            print(error)

    @property
    def calib_path(self) -> "Path":
        """Directory for calibration run."""
        return self._calib_path

    @property
    def valid_path(self) -> "Path":
        """Directory for validation run."""
        return self._valid_path


class NoModel(BaseModel):
    """A simple empty model data class for testing."""

    type: Literal["none"]


class Model(BaseModel):
    """Composition data class for defining a model configuration."""

    model: Annotated[
        Union[Ngen, NoModel, NoCalibModel],
        Field(discriminator="type"),  # <-- v2 style discriminated union
    ]


class NoCalibModel(ModelExec):
    type: Literal["nocalib"] = "nocalib"
    strategy: Optional[str] = Field(default="uniform")

    realization: Path
    catchments: Path
    nexus: Path
    obsflow: Path
    nwmflow: Path
    crosswalk: Path
    _precip: gpd.GeoDataFrame = None
    objective_score: Optional[float] = None
    _output_iter_file: Path = PrivateAttr(default=None)
    _output_best_iter_file: Path = PrivateAttr(default=None)
    _output_last_iter_file: Path = PrivateAttr(default=None)
    evaluation_range: Optional[List[datetime]] = None
    metrics: Optional[Dict[str, float]] = None

    def create_validation_configs(self, agent):
        """
        For NoCalibModel, generate dummy 'valid_control' and 'valid_best' config YAMLs
        and corresponding realization files, so validation workflow runs as expected.
        """
        from pathlib import Path

        import yaml

        logger.info("[NoCalibModel] Generating validation config files...")

        basin_id = self.eval_params.basinID
        valid_path = agent.valid_path
        input_yaml_path = agent.yaml_file

        for tag in ["valid_control", "valid_best"]:
            yaml_out = Path(valid_path) / f"{basin_id}_config_{tag}.yaml"
            realization_out = (
                Path(valid_path) / f"{basin_id}_realization_config_bmi_{tag}.json"
            )

            # Copy realization file to validation path
            shutil.copy2(self.realization, realization_out)

            # Load original YAML configuration
            with open(input_yaml_path, "r") as f:
                config = yaml.safe_load(f)

            # Update general section for validation run
            config["general"]["name"] = tag
            config["general"]["yaml_file"] = str(yaml_out)
            config["model"]["realization"] = str(realization_out)

            # Update simulation time period to validation period if specified
            if "time" in config:
                # Use validation start/end times if provided, otherwise leave as is
                if (
                    self.eval_params.valid_start_time
                    and self.eval_params.valid_end_time
                ):
                    config["time"]["start_time"] = (
                        self.eval_params.valid_start_time.strftime("%Y-%m-%d %H:%M:%S")
                    )
                    config["time"]["end_time"] = (
                        self.eval_params.valid_end_time.strftime("%Y-%m-%d %H:%M:%S")
                    )
                if (
                    self.eval_params.valid_eval_start_time
                    and self.eval_params.valid_eval_end_time
                ):
                    # If separate evaluation window for validation is provided
                    config["time"]["evaluation_start"] = (
                        self.eval_params.valid_eval_start_time.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    )
                    config["time"]["evaluation_end"] = (
                        self.eval_params.valid_eval_end_time.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    )

            # Remove calibration params if present (not needed for NoCalibModel validation configs)
            config["model"].pop("params", None)

            # Write new YAML file
            with open(yaml_out, "w") as f:
                yaml.dump(config, f)
            logger.info(f"[NoCalibModel] Config file for {tag} created at {yaml_out}")

    def get_working_basins_from_crosswalk(self, crosswalk_path, target_basin_id):
        with open(crosswalk_path, "r") as f:
            crosswalk = json.load(f)

        matched = [
            key.split("-")[-1]
            for key, value in crosswalk.items()
            if str(value.get("Gage_no")) == str(target_basin_id)
        ]

        return matched

    def get_sim_df(self, _output_file, _wb_lst) -> "DataFrame":
        """
        The model output hydrograph for this catchment
        This re-reads the output file each call, as the output for given calibration catchment changes
        for each calibration iteration. If it doesn't exist, should return None
        """
        try:
            # Read the routed flow at the eval_nexus
            ncvar = netCDF4.Dataset(_output_file, "r")
            fid_index = [
                list(ncvar["feature_id"][0:]).index(int(fid)) for fid in _wb_lst
            ]
            _output = pd.DataFrame(
                data={
                    "sim_flow": pd.DataFrame(
                        ncvar["flow"][fid_index], index=fid_index
                    ).T.sum(axis=1)
                }
            )

            # Get date range
            times = netCDF4.num2date(
                ncvar["time"][:],
                units=ncvar["time"].units,
            )

            dt_range = pd.DatetimeIndex([pd.Timestamp(t.isoformat()) for t in times])
            _output.index = dt_range
            _output.index.name = "Time"
            _output = _output.resample("1h").first()

            logger.info("Simulation results ready (DataFrame populated)")
            hydrograph = _output

        except FileNotFoundError:
            logger.info(os.listdir(os.getcwd()))
            logger.info("Output is currently empty.")
            hydrograph = None
        except Exception as e:
            raise (e)

        if hydrograph is None or hydrograph.empty:
            msg = "Simulated hydrograph is unavailable or empty."
            logger.error(msg)
            raise ValueError(msg)
        
        return hydrograph

    def postprocess_single_calibration_output(self, agent):
        import logging
        import os
        import shutil
        from pathlib import Path
        from types import SimpleNamespace

        import pandas as pd
        from nwm_metrics.metric_functions import calculate_metrics

        from calib.plot_output import plot_calib_output
        from calib.utils import report_to_ngencerf

        basin_id = agent.model.eval_params.basinID
        workdir = agent.job.workdir
        calibration_dir = Path(workdir).parent
        plot_iter_path = Path(workdir) / "Plot_Iteration"
        output_iter_path = Path(workdir) / "Output_Iteration"
        plot_iter_path.mkdir(exist_ok=True)
        output_iter_path.mkdir(parents=True, exist_ok=True)

        output_dir = Path(workdir)

        sim_streamflow_col = "sim_flow"
        obs_flow_col = "obs_flow"

        netcdf_files = list(workdir.glob("troute_output_*.nc"))
        if not netcdf_files:
            raise FileNotFoundError(
                f"No troute_output_*.nc file found in {os.getcwd()}."
            )
        trout_file = netcdf_files[0]
        _wb_lst = self.get_working_basins_from_crosswalk(
            self.crosswalk, agent.model.eval_params.basinID
        )

        try:
            sim_df = self.get_sim_df(trout_file, _wb_lst)
            sim_df.reset_index()
            if "Time" in sim_df.columns:
                sim_df = sim_df.set_index("Time")
            sim_df.columns = [sim_streamflow_col]
            sim_df.index = pd.to_datetime(sim_df.index)
            logger.info(f"sim_df : \n{sim_df}")

            # Load observed data
            obs_df = pd.read_csv(self.obsflow, parse_dates=["value_date"])

            # if obs is empty, raise an error
            if obs_df.empty:
                msg = f"Streamflow observation file is empty: {self.obsflow}"
                logger.error(msg)
                raise ValueError(msg)
            
            obs_df = obs_df.rename(
                columns={"value_date": "Time", obs_df.columns[1]: obs_flow_col}
            ).set_index("Time")
            obs_df.columns = [obs_flow_col]
            obs_df.index = pd.to_datetime(obs_df.index)
            obs_df = obs_df[
                (obs_df.index >= sim_df.index.min())
                & (obs_df.index <= sim_df.index.max())
            ]

            df_all = pd.merge(obs_df, sim_df, left_index=True, right_index=True)

            metrics = calculate_metrics(
                df_all[obs_flow_col],
                df_all[sim_streamflow_col],
                threshold_categorical=self.eval_params.threshold_categorical,
                threshold_event=self.eval_params.threshold_event,
            )
            metrics_df = pd.DataFrame([metrics])
            metrics_df.insert(0, "iteration", 0, True)

            metrics_best_path = workdir / f"{basin_id}_metrics_iteration.csv"
            metrics_df.to_csv(metrics_best_path, index=False)

        except Exception as e:
            logger.warning(f"Metrics or plot failed: {e}")
            logger.info(traceback.format_exc())

        self._output_iter_file = str(
            output_iter_path / f"{basin_id}_output_iteration_0000.csv"
        )
        self._output_best_iter_file = str(
            output_iter_path / f"{basin_id}_output_best_iteration.csv"
        )
        self._output_last_iter_file = str(
            output_iter_path / f"{basin_id}_output_last_iteration.csv"
        )

        sim_df.to_csv(self._output_iter_file)
        sim_df.to_csv(self._output_best_iter_file)
        sim_df.to_csv(self._output_last_iter_file)
        logger.info(
            f"[NoCalibModel] Wrote: {self._output_iter_file}, {self._output_best_iter_file}, {self._output_best_iter_file}"
        )

        for file in output_iter_path.glob("*.csv"):
            shutil.copy(file, workdir)

        # Move cat-* and nex-*output.csv to Output_Calib
        output_calib_path = workdir / "Output_Calib"
        output_calib_path.mkdir(parents=True, exist_ok=True)

        for file in workdir.glob("cat-*.csv"):
            shutil.move(file, output_calib_path)
        for file in workdir.glob("nex-*_output.csv"):
            shutil.move(file, output_calib_path)

        # Dummy parameter and objfun DataFrames
        param_df = pd.DataFrame()
        objfun_df = pd.DataFrame()

        # Get time range from streamflow index
        date_range = (df_all.index.min(), df_all.index.max())

        try:
            output = sim_df
            observed = obs_df

            # Ensure column names for _calc_metrics expectations
            if isinstance(output, pd.Series):
                output = output.to_frame(name=sim_streamflow_col)
            else:
                output = output.rename(columns={output.columns[0]: sim_streamflow_col})

            if isinstance(observed, pd.Series):
                observed = observed.to_frame(name=obs_flow_col)
            else:
                observed = observed.rename(columns={observed.columns[0]: obs_flow_col})

            # Create calibration_object with required fields
            calibration_object = SimpleNamespace(
                output=output,
                threshold_categorical=self.eval_params.threshold_categorical,
                threshold_event=self.eval_params.threshold_event,
                streamflow_name=sim_streamflow_col,
                observed=observed,
                station_name=basin_id,
                metric_iter_file=metrics_best_path,
                best_params=0,
                cost_iter_file=None,
                param_iter_file=metrics_best_path,
                save_plot_iter_flag=False,
                basinID=basin_id,
                iter_num=0,
                date_range=date_range,
            )
            plot_calib_output(0, calibration_object, agent, single_exec=True)

            report_to_ngencerf(agent)

        except Exception as e:
            logger.warning(f"Calibration plot generation failed: {e}")
            logger.info(traceback.format_exc())

        logger.info("[NoCalibModel] All calibration plots generated in Plot_Iteration.")

    def postprocess_single_validation_output(self, agent: "Agent", valid_suffix=None):
        """
            Post-process validation output for NoCalibModel.

            This includes:
            -  Copying outputs from the run directory to Output_Valid
            - Computing metrics using metric_functions
        -     Generating plots via plot_functions
        """

        import shutil
        from pathlib import Path
        from types import SimpleNamespace

        import pandas as pd

        from calib.plot_output import plot_valid_output
        from calib.search import _calc_metrics

        workdir = Path(agent.job.workdir)
        basin_id = self.basinID
        output_valid_dir = workdir / "Output_Valid"
        output_valid_dir.mkdir(exist_ok=True)
        output_parent_path = Path(workdir).parent

        sim_streamflow_col = "sim_flow"
        obs_flow_col = "obs_flow"
        if not valid_suffix:
            valid_suffix = agent.run_name

        # Get the simulation output from trout
        netcdf_files = list(workdir.glob("troute_output_*.nc"))
        if not netcdf_files:
            raise FileNotFoundError(
                f"No troute_output_*.nc file found in {os.getcwd()}."
            )
        trout_file = netcdf_files[0]
        _wb_lst = self.get_working_basins_from_crosswalk(
            self.crosswalk, agent.model.eval_params.basinID
        )

        try:
            sim_df = self.get_sim_df(trout_file, _wb_lst)
            sim_df.reset_index()
            if "Time" in sim_df.columns:
                sim_df = sim_df.set_index("Time")
            sim_df.columns = [sim_streamflow_col]
            sim_df.index = pd.to_datetime(sim_df.index)
            logger.info(f"sim_df : \n{sim_df}")

            # Load observed data
            obs_df = pd.read_csv(self.obsflow, parse_dates=["value_date"])
            obs_df = obs_df.rename(
                columns={"value_date": "Time", obs_df.columns[1]: obs_flow_col}
            ).set_index("Time")
            obs_df.columns = [obs_flow_col]
            obs_df.index = pd.to_datetime(obs_df.index)
            obs_df = obs_df[
                (obs_df.index >= sim_df.index.min())
                & (obs_df.index <= sim_df.index.max())
            ]

            df_all = pd.merge(obs_df, sim_df, left_index=True, right_index=True)

            self.eval_params._eval_range = (
                pd.to_datetime(self.eval_params.evaluation_start),
                pd.to_datetime(self.eval_params.evaluation_stop),
            )
            self.eval_params._valid_eval_range = (
                pd.to_datetime(self.eval_params.valid_eval_start_time),
                pd.to_datetime(self.eval_params.valid_eval_end_time),
            )
            self.eval_params._full_eval_range = (
                pd.to_datetime(self.eval_params.full_eval_start_time),
                pd.to_datetime(self.eval_params.full_eval_end_time),
            )

            output = sim_df
            observed = obs_df

            # Ensure column names for _calc_metrics expectations
            if isinstance(output, pd.Series):
                output = output.to_frame(name=sim_streamflow_col)
            else:
                output = output.rename(columns={output.columns[0]: sim_streamflow_col})

            if isinstance(observed, pd.Series):
                observed = observed.to_frame(name=obs_flow_col)
            else:
                observed = observed.rename(columns={observed.columns[0]: obs_flow_col})

            # Create dummy calibration object
            calibration_object = SimpleNamespace(
                output=output,
                observed=observed,  # self.observed,
                station_name=basin_id,
                basinID=basin_id,
                evaluation_range=self.eval_params._eval_range,
                valid_evaluation_range=self.eval_params._valid_eval_range,
                full_evaluation_range=self.eval_params._full_eval_range,
                streamflow_name=sim_streamflow_col,
                threshold_categorical=self.eval_params.threshold_categorical,
                threshold_event=self.eval_params.threshold_event,
            )
            time_period = {
                "calib": calibration_object.evaluation_range,
                "valid": calibration_object.valid_evaluation_range,
                "full": calibration_object.full_evaluation_range,
            }

            # Compute metrics for each time period
            metrics = pd.DataFrame()
            for period_name, date_range in time_period.items():
                result = _calc_metrics(
                    calibration_object.output,
                    calibration_object.observed,
                    date_range,
                    calibration_object.threshold_categorical,
                    calibration_object.threshold_event,
                )
                row = {"run": valid_suffix, "period": period_name, **result}
                metrics = pd.concat([metrics, pd.DataFrame([row])], ignore_index=True)

            # Save metrics to CSV
            metrics_path = (
                Path(agent._valid_path) / f"{basin_id}_metrics_{valid_suffix}.csv"
            )
            metrics.to_csv(metrics_path, index=False)

            # df_all = pd.concat([obs_df, sim_df], axis=1).dropna()
        except Exception as e:
            logger.info(f"metrics calculation error : {e}")
            logger.info(traceback.format_exc())

        # Step 3: Save to Output_Iteration
        output_iter_file = output_parent_path / f"{basin_id}_output_{valid_suffix}.csv"
        sim_df.to_csv(output_iter_file)
        logger.info(f"[NoCalibModel] Wrote: {output_iter_file}")

        # Copy and rename output files
        for file in workdir.glob("*"):
            if file.suffix == ".csv" and ("cat-" in file.name or "nex-" in file.name):
                parts = file.name.split(".")[0].split("-")
                if len(parts) >= 2:
                    prefix = parts[0]  # cat or nex
                    catch_id = parts[1].split("_")[
                        0
                    ]  # extract ID and remove existing suffix if present
                    new_name = f"{prefix}-{catch_id}_{valid_suffix}.csv"
                    shutil.move(file, output_valid_dir / new_name)

        # Plottimg is not part of valid control workflow
        if valid_suffix != "valid_best":
            logger.info(
                "[NoCalibModel] Post-processing of single-run valid control output completed."
            )
            return

        obs_path = Path(self.obsflow)

        # nwm_retro data
        try:
            if agent.nwmflow_file != "":
                if os.path.exists(agent.nwmflow_file):
                    logger.info(
                        f"Read NWM retrospective streamflow simulation from: {agent.nwmflow_file}"
                    )
                    nwm = pd.read_csv(agent.nwmflow_file)
                    nwm.columns = ["value_date", "sim_flow"]
                    nwm["value_date"] = pd.DatetimeIndex(nwm["value_date"])
                    agent.nwmflow = nwm.set_index("value_date")
                else:
                    logger.error(f"File does not exist: {agent.nwmflow_file}")
            else:
                agent.nwmflow = None
                agent.nwmflow = self.nwmflow

            df_nwm_metrics = pd.DataFrame()

            observed = agent.nwmflow

            if isinstance(observed, pd.Series):
                observed = observed.to_frame(name="obs_flow")
            else:
                observed = observed.rename(columns={observed.columns[0]: "obs_flow"})

            for period_name, date_range in time_period.items():
                result = _calc_metrics(
                    calibration_object.output,
                    observed,
                    date_range,
                    calibration_object.threshold_categorical,
                    calibration_object.threshold_event,
                )
                nwm_row = {
                    "run": "nwm_retro",
                    "period": period_name,
                    **result,
                }  # or modify result if needed for NWM
                df_nwm_metrics = pd.concat(
                    [df_nwm_metrics, pd.DataFrame([nwm_row])], ignore_index=True
                )
            nwm_metrics_path = (
                Path(agent._valid_path) / f"{basin_id}_metrics_nwm_retro.csv"
            )
            df_nwm_metrics.to_csv(nwm_metrics_path, index=False)
        except Exception as e:
            logger.warning(f"Error computing nwm_retro metrics : {e}")
            logger.info(traceback.format_exc())

        runs = []
        try:
            combined_metrics = []
            for rname in ["nwm_retro", "valid_control", "valid_best"]:
                mfile = Path(agent.valid_path) / f"{basin_id}_metrics_{rname}.csv"
                if mfile.exists():
                    df = pd.read_csv(mfile)
                    if "objFunVal" not in df.columns:
                        df["objFunVal"] = df["KGE"] if "KGE" in df.columns else 0.0
                    if "CORR" not in df.columns:
                        df["CORR"] = 0.0
                    combined_metrics.append(df)
                    runs.append(rname)
                else:
                    logger.warning(f"Missing metrics file: {mfile}")

            if combined_metrics:
                combined_df = pd.concat(combined_metrics, ignore_index=True)

                # Drop excess columns if needed
                drop_cols = ["run_type", "sim_flow", "obs_flow"]
                combined_df = combined_df.drop(
                    columns=[c for c in drop_cols if c in combined_df.columns]
                )

                combined_path = (
                    Path(agent.valid_path) / f"{basin_id}_metrics_valid_run.csv"
                )
                combined_df.to_csv(combined_path, index=False)
                logger.info(f"Saved combined validation metrics to {combined_path}")
        except Exception as e:
            logger.warning(f"Failed to create combined metrics_valid_run.csv: {e}")
            logger.info(traceback.format_exc())

        try:
            # Clone the agent with all fields + override df_precip
            agent_fixed = SimpleNamespace(
                **vars(agent),
                valid_path=agent.valid_path,
                valid_path_plot=agent.valid_path_plot,
            )

            # Call plot_valid_output to produce all standard plots
            plot_valid_output(
                calibration_object=calibration_object,
                agent=agent_fixed,
                runs=runs,
                time_period=time_period,
            )
        except Exception as e:
            logger.warning(f"plot_valid_output failed: {e}")
            logger.info(traceback.format_exc())

        logger.info("[NoCalibModel] All validation plots generated in Plot_Valid.")

    def get_args(self) -> str:
        return f"{self.catchments} all {self.nexus} all {self.realization}"

    def update_config(
        self, i: int, params: pd.DataFrame, id=None, path: Path = Path(".")
    ):
        # No-op for single-run models
        pass

    def resolve_paths(self):
        self.realization = self.realization.resolve()
        self.catchments = self.catchments.resolve()
        self.nexus = self.nexus.resolve()
        self.obsflow = self.obsflow.resolve()
        self.nwmflow = self.nwmflow.resolve()
        self.crosswalk = self.crosswalk.resolve()

    @property
    def adjustables(self):
        return []

    @property
    def observed(self) -> pd.DataFrame:
        return pd.read_csv(self.obsflow, index_col=0, parse_dates=True)

    @property
    def evaluation_range(self):
        return self.eval_params._eval_range

    @property
    def threshold_categorical(self):
        return self.eval_params.threshold_categorical

    @property
    def threshold_event(self):
        return self.eval_params.threshold_event

    @property
    def realization_file(self) -> Path:
        return self.realization

    @property
    def output(self) -> pd.DataFrame:
        if not self._output_iter_file or not self._output_iter_file.exists():
            raise FileNotFoundError(
                f"No simulation output file found at: {self._output_iter_file}"
            )
        import pandas as pd

        return pd.read_csv(self._output_iter_file, index_col=0, parse_dates=True)

    @property
    def basinID(self):
        return self.eval_params.basinID

    @property
    def user(self):
        return None

    def write_run_complete_file(self, run_name: str, workdir: Path):
        """Write a simple completion file for single-run NoCalibModel."""
        complete_file = workdir / f"{run_name}_complete.txt"
        with open(complete_file, "w") as f:
            f.write("Single-run execution complete.\n")

    '''
    def write_iteration_outputs(self, output_dir, metrics: dict, obj_score: float):
        """
        Save metrics, objective logs, dummy params, and standard plots.
        """
        i = 0
        basinID = self.eval_params.basinID
        df = self.output
        
        output_dir = Path(output_dir)
        output_iter_path = output_dir / "Output_Iteration"
        plot_iter_path = output_dir / "Plot_Iteration"
        calib_path = output_dir / "Output_Calib"
        output_iter_path.mkdir(parents=True, exist_ok=True)
        plot_iter_path.mkdir(parents=True, exist_ok=True)
        calib_path.mkdir(parents=True, exist_ok=True)

        # Write CSVs
        df.to_csv(str(output_iter_path / f"{basinID}_output_iteration_{i:04d}.csv"))
        df.to_csv(str(output_iter_path / f"{basinID}_output_best_iteration.csv"))
        df.to_csv(str(output_iter_path / f"{basinID}_output_last_iteration.csv"))

        # Metrics and logs
        self.eval_params.write_metric_iter_file(i, obj_score, metrics)
        self.eval_params.write_objective_log_file(i, obj_score)

        dummy_param_df = pd.DataFrame([{
            "model": "nocalib",
            "param": "none",
            str(i): 0.0
        }])
        self.eval_params.write_param_iter_file(i, dummy_param_df)
        self.eval_params.write_param_all_file(i, dummy_param_df)
        self.eval_params.write_last_iteration(i)
        # self.eval_params.write_cost_iter_file(i, calib_path)
        # self.eval_params.write_run_complete_file("calib", calib_path)

        # Plotting
        if self.eval_params.save_plot_iter_flag:
            from calib.plot_output import plot_metric, plot_obj_fun, plot_streamflow, plot_scatterplot, plot_fdc
            plot_metric(agent)
            plot_obj_fun(agent)
            plot_streamflow(agent, df, self.observed, basinID, plot_iter_path, title="Streamflow")
            plot_scatterplot(agent, df, self.observed, basinID, plot_iter_path)
            plot_fdc(agent, df, self.observed, basinID, plot_iter_path)
    '''

    @property
    def df_nwm(self):
        if not hasattr(self, "nwmflow"):
            raise AttributeError("No NWM flow file configured.")
        path = Path(self.nwmflow)
        if not path.exists():
            raise FileNotFoundError(f"NWM flow file not found: {path}")
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df = df.rename(columns={df.columns[0]: "nwm_retro"})
        return df

    def write_cost_iter_file(self, i, path):
        # No-op for single-run NoCalibModel
        pass


# Model.update_forward_refs()
Model.model_rebuild()
