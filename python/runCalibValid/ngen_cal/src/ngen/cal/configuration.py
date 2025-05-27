"""
This module implements several classes to hold generation confugrations. 

@author: Nels Frazer, Xia Feng
"""

from __future__ import annotations #for pydnaitc 

import logging
import os
from pathlib import Path
from typing import Optional, Union
try: #to get literal in python 3.7, it was added to typing in 3.8
    from typing import Literal
except ImportError:
    from typing_extensions import Literal

from pydantic import BaseModel, Field, DirectoryPath, PrivateAttr

from .model import PosInt
from .model import ModelExec
from .ngen import Ngen
from .strategy import Estimation, Sensitivity
from .search import _calc_metrics as calculate_all_metrics
import pandas as pd
import glob
import os
import traceback
import numpy as np


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s,%(msecs)d %(levelname)s: %(message)s",
    datefmt="%H:%M:%S")


class General(BaseModel):
    """General configuration class."""
    # Required fields
    strategy: Union[Estimation, Sensitivity] = Field(discriminator='type')
    iterations: int
    # Fields with reasonable defaults
    restart: bool = False
    start_iteration: PosInt = 0
    workdir: DirectoryPath = Path("./")
    name: str 
    yaml_file: Path
    # Optional fields
    log: Optional[bool] = False
    parameter_log_file: Optional[Path]
    objective_log_file: Optional[Path]
    random_seed: Optional[int]
    calibration_run_id: Optional[int]
    ngen_cerf: Optional[bool]
    auth_token: Optional[str]
    # Private
    _calib_path: Path
    _valid_path: Path

    class Config:
        """Override configuration for pydantic BaseModel."""
        underscore_attrs_are_private = True
        use_enum_values = True
        smart_union = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._calib_path = os.path.join(str(self.workdir) + '/Output', 'Calibration_Run')
        self._valid_path = os.path.join(str(self.workdir) + '/Output', 'Validation_Run')
        try:
            os.makedirs(self._calib_path, exist_ok=True)
            os.makedirs(self._valid_path, exist_ok=True)
        except OSError as error:
            print(error)

    @property
    def calib_path(self) -> 'Path':
        """Directory for calibration run."""
        return self._calib_path

    @property
    def valid_path(self) -> 'Path':
        """Directory for validation run."""
        return self._valid_path



class NoModel(BaseModel):
    """A simple empty model data class for testing."""
    type: Literal['none']


class Model(BaseModel):
    """Composition data class for defining a model configuration."""
    # model: Union[Ngen, NoModel] = Field(discriminator='type')
    model: Union[Ngen, NoModel, NoCalibModel] = Field(discriminator='type')



from pathlib import Path
import pandas as pd
import shutil
import glob
import warnings
import logging
import geopandas as gpd

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)



from .model import BaseModel
#from .metrics import calculate_all_metrics
from . import plot_output

#logger = logging.getLogger("NGEN_CAL")


# ... [existing imports and code above remain unchanged] ...

class NoCalibModel(ModelExec):
    type: Literal["nocalib"] = "nocalib"
    strategy: Optional[str] = Field(default="uniform")

    realization: Path
    catchments: Path
    nexus: Path
    obsflow: Path
    nwmflow: Path
    _precip: gpd.GeoDataFrame = None
    objective_score: Optional[float] = None 
    _output_iter_file: Path = PrivateAttr(default=None)
    _output_best_iter_file: Path = PrivateAttr(default=None)
    _output_last_iter_file: Path = PrivateAttr(default=None)
    evaluation_range: Optional[List[datetime]] = None
    metrics: Optional[Dict[str, float]] = None

    def execute_model(self):
        """
        Execute the model run for single-execution validation.
        This mirrors the interface of calibrated models.
        """
        logger.info("[NoCalibModel] Executing model (validation run)")
        self.run(self.get_args())

    def create_validation_configs(self, agent):
        """
        For NoCalibModel, generate dummy 'valid_control' and 'valid_best' config YAMLs
        and corresponding realization files, so validation workflow runs as expected.
        """
        import yaml
        from pathlib import Path

        logger.info("[NoCalibModel] Generating validation config files...")

        basin_id = self.eval_params.basinID
        valid_path = agent.valid_path
        input_yaml_path = agent.yaml_file

        for tag in ["valid_control", "valid_best"]:
            yaml_out = Path(valid_path) / f"{basin_id}_config_{tag}.yaml"
            realization_out = Path(valid_path) / f"{basin_id}_realization_config_bmi_{tag}.json"

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
                if self.eval_params.valid_start_time and self.eval_params.valid_end_time:
                    config["time"]["start_time"] = self.eval_params.valid_start_time.strftime("%Y-%m-%d %H:%M:%S")
                    config["time"]["end_time"] = self.eval_params.valid_end_time.strftime("%Y-%m-%d %H:%M:%S")
                if self.eval_params.valid_eval_start_time and self.eval_params.valid_eval_end_time:
                    # If separate evaluation window for validation is provided
                    config["time"]["evaluation_start"] = self.eval_params.valid_eval_start_time.strftime("%Y-%m-%d %H:%M:%S")
                    config["time"]["evaluation_end"] = self.eval_params.valid_eval_end_time.strftime("%Y-%m-%d %H:%M:%S")

            # Remove calibration params if present (not needed for NoCalibModel validation configs)
            config["model"].pop("params", None)

            # Write new YAML file
            with open(yaml_out, "w") as f:
                yaml.dump(config, f)
            logger.info(f"[NoCalibModel] Config file for {tag} created at {yaml_out}")
    
    def read_streamflow(self, file_path):
        """Read a streamflow CSV with 'Time' column as datetime index."""
        import pandas as pd
        df = pd.read_csv(file_path)
        if "Time" in df.columns:
            df["Time"] = pd.to_datetime(df["Time"])
            df.set_index("Time", inplace=True)
        else:
            df.index.name = "Time"
        return df


    def postprocess_single_calibration_output(self, agent):
        import os
        import shutil
        import pandas as pd
        import copy
        import csv
        from pathlib import Path
        from ngen.cal import metric_functions as mf
        from ngen.cal import plot_functions as pf
        import logging

        basin_id = agent.model.eval_params.basinID
        workdir = agent.job.workdir
        calibration_dir = Path(workdir).parent
        plot_iter_path = Path(workdir) / "Plot_Iteration"
        output_iter_path = Path(workdir)/"Output_Iteration"
        plot_iter_path.mkdir(exist_ok=True)
        output_iter_path.mkdir(parents=True, exist_ok=True)

        logger = logging.getLogger("NGEN_CAL")
        output_dir = Path(workdir)

         # Step 1: Get the fallback NEX CSV file
        matches = list(workdir.glob("nex-*_output.csv"))
        if not matches:
            raise FileNotFoundError(f"No NEX output CSV found in {workdir}")
        nex_file = matches[0]
        warnings.warn(f"Using fallback output file: {nex_file.name}", RuntimeWarning)

        # Step 2: Read the fallback file assuming no headers, manually assign
        df_raw = pd.read_csv(nex_file, header=None, names=["Time", "sim_flow"], parse_dates=["Time"])
        df_raw.set_index("Time", inplace=True)

        # Step 3: Save to Output_Iteration
        self._output_iter_file = str(output_iter_path / f"{basin_id}_output_iteration_0000.csv")
        self._output_best_iter_file = str(output_iter_path / f"{basin_id}_output_best_iteration.csv")
        self._output_last_iter_file = str(output_iter_path / f"{basin_id}_output_last_iteration.csv")

        df_raw.to_csv(self._output_iter_file)
        df_raw.to_csv(self._output_best_iter_file)
        df_raw.to_csv(self._output_last_iter_file)
        logger.info(f"[NoCalibModel] Wrote: {self._output_iter_file}, {self._output_best_iter_file}, {self._output_best_iter_file}")

        # Step 4: Copy cat-* and nex-*output.csv to Output_Calib
        output_calib_path = workdir / "Output_Calib"
        output_calib_path.mkdir(parents=True, exist_ok=True)

        for file in workdir.glob("cat-*.csv"):
            shutil.move(file, output_calib_path)
        for file in workdir.glob("nex-*_output.csv"):
            shutil.move(file, output_calib_path)

        # Metric calculation
        sim_file = output_iter_path / f"{basin_id}_output_best_iteration.csv"
        obs_file = Path(self.obsflow)
        y_true = pd.read_csv(obs_file, index_col=0, parse_dates=True).iloc[:, 0]
        y_pred = pd.read_csv(sim_file, index_col=0, parse_dates=True).iloc[:, 0]
        y_true, y_pred = y_true.align(y_pred, join="inner")
        metrics = mf.calculate_all_metrics(y_true, y_pred)
        # metrics["catchment_id"] = basin_id
        metrics["iteration"] = 0
        metrics_df = pd.DataFrame([metrics])
        logger.info(f"Calibration metrics 0: \n{metrics_df}")
        metrics_best_path = workdir / f"{basin_id}_metrics_iteration.csv"
        metrics_df.to_csv(metrics_best_path, index=False)
        # shutil.copy(metrics_path, plot_iter_path / metrics_path.name)


        try:


            obs_df = pd.read_csv(obs_file, parse_dates=["value_date"])
            obs_df = obs_df.rename(columns={"value_date": "Time", obs_df.columns[1]: "Observation"}).set_index("Time")

            # === Try to locate the simulation file ===
            nex_file = self._output_iter_file
            # === Use header detection fix ===
            with open(nex_file, 'r') as f:
                sample = f.read(1024)
                f.seek(0)
                has_header = csv.Sniffer().has_header(sample)

            if has_header:
                sim_df = pd.read_csv(nex_file, parse_dates=["Time"])
                if "Time" in sim_df.columns:
                    sim_df = sim_df.set_index("Time")
                sim_df.columns = ["Simulated"]
            else:
                sim_df = pd.read_csv(nex_file, header=None, names=["Time", "Simulated"], parse_dates=["Time"])
                sim_df = sim_df.set_index("Time")

            # === Join and calculate metrics ===
            df_all = pd.concat([obs_df, sim_df], axis=1).dropna()
            metrics = mf.calculate_all_metrics(df_all["Observation"], df_all["Simulated"])
            metrics_df = pd.DataFrame([metrics])
            metrics_df.insert(0, "iteration", 0, True)

            logger.info(f"Calibration metrics 1: \n{metrics_df}")

            metrics_path = workdir / f"{basin_id}_metrics_iteration.csv"
            metrics_df.to_csv(metrics_path, index=False)

        except Exception as e:
            logger.warning(f"Metrics or plot failed: {e}")
            logger.info(traceback.format_exc())



        # Cost function
        try:
            cost_dir = output_dir / "Output_Calib"
            cost_dir.mkdir(exist_ok=True)
            cost_path = cost_dir / f"{basin_id}_output_cost.csv"
            obj_key = self.eval_params.objective.upper()
            obj_value = metrics.get(obj_key, list(metrics.values())[0])
            cost_df = pd.DataFrame({self.eval_params.objective: [obj_value]})
            cost_df.to_csv(cost_path, index=False)
        except Exception as e:
            try:
                cost_df = pd.DataFrame({self.eval_params.objective: [metrics[self.eval_params.objective]]})
                cost_df.to_csv(output_calib / f"{basin_id}_output_cost.csv", index=False)
            except Exception as e:
                logger.warning(f"Cost file generation failed: {e}")
                logger.info(traceback.format_exc())
      

        # Load streamflow time series
        df_obs = pd.read_csv(obs_file, index_col=0, parse_dates=True)
        df_iter = pd.read_csv(output_iter_path / f"{basin_id}_output_iteration_0000.csv", index_col=0, parse_dates=True)
        df_best = pd.read_csv(output_iter_path / f"{basin_id}_output_best_iteration.csv", index_col=0, parse_dates=True)
        df_last = pd.read_csv(output_iter_path / f"{basin_id}_output_last_iteration.csv", index_col=0, parse_dates=True)

        for file in output_iter_path.glob("*.csv"):
            shutil.copy(file, workdir)

        df_obs.columns = ['Observation']
        df_iter.columns = ['Control Run']
        df_best.columns = ['Best Run']
        df_last.columns = ['Last Run']

        # temporary scaling to see the graph
        scale_factor = df_obs.mean().values[0] / df_best.mean().values[0]
        df_best *= scale_factor
        df_last *= scale_factor
        df_iter *= scale_factor

        df_best_sim = df_best.copy()
        df_best_sim.columns = ['Simulated']
        df_all = pd.concat([df_obs, df_best, df_best_sim], axis=1)
        df_all.index.name = "Time"
        df_all = df_all.dropna(subset=["Observation", "Simulated"])


        try:
            pf.plot_obj_fun(agent)
        except Exception as e:
            logger.warning(f"plot_obj_fun : {e}")
            logger.info(traceback.format_exc())


        # Hydrograph
        try:
            df_hydro = df_all.reset_index()
            pf.plot_streamflow(
                df=copy.deepcopy(df_hydro),
                plotfile=plot_iter_path / f"{basin_id}_hydrograph_iteration.png",
                title=f"Hydrograph (Calibration Iteration)\n{basin_id}"
            )
        except Exception as e:
            logger.warning(f"plot_streamflow : {e}")
            logger.info(traceback.format_exc())

        # Flow Duration Curve
        try:
            df_fdc = df_all[["Observation", "Simulated"]].copy()
            df_fdc = df_fdc.reset_index()
            #df_fdc = df_fdc[["Observation", "Simulated"]]  # Drop 'Time' again if needed
            pf.plot_fdc_calib(
                df=df_fdc,
                plotfile=plot_iter_path / f"{basin_id}_fdc_iteration.png",
                title="Flow Duration Curve (Calibration Iteration)"
            )
        except Exception as e:
            logger.warning(f"plot_fdc_calib : {e}")
            logger.info(traceback.format_exc())

        # Scatter Plot
        try:
            df_all["Simulated"] = df_all["Best Run"]
            df_scatter = df_all.reset_index()

            pf.scatterplot_streamflow(
                df=df_scatter[["Time", "Observation", "Simulated"]],
                plotfile=plot_iter_path / f"{basin_id}_scatterplot_streamflow_iterations.png",
                title="Scatterplot Streamflow Curve (Calibration Iteration)"
            )
        except Exception as e:
            logging.getLogger(__name__).warning(f"Scatterpl;ot Streamflow plot skipped: {e}")
            logger.info(traceback.format_exc())

        # Streamflow + Precip
        try:
            df_precip = self.df_precip.reset_index()
            pf.plot_streamflow_precipitation(
                df=copy.deepcopy(df_hydro),
                dfp=df_precip,
                plotfile=plot_iter_path / f"{basin_id}_streamflow_precip_iteration.png",
                title=f"Streamflow + Precipitation (Calibration Iteration)"
            )
        except Exception as e:
            logging.getLogger(__name__).warning(f"Precipitation plot skipped: {e}")
            logger.info(traceback.format_exc())

        '''
        df = pd.read_csv(metrics_best_path)
        for col in df.columns:
            if isinstance(df.at[0, col], np.ndarray):
                df[col] = df[col].apply(lambda x: x[0] if isinstance(x, np.ndarray) else x)
        
        df.to_csv(metrics_best_path, index=False)
        logger.info(f"written updated metrics df to {metrics_best_path}")
        '''

        # Obj Fun
        try:
            pf.scatterplot_objfun(
                metric_file=metrics_best_path,
                plotfile=plot_iter_path / f"{basin_id}_objfun_iteration.png",
                objective_fun_column=self.eval_params.objective.upper(),
                best_iteration=0,
                title="Objective Function vs Iteration",
            )
        except Exception as e:
            logger,info(metrics_best_path)
            logger.warning(f"scatterplot_objfun failed: {e}")
            logger.info(traceback.format_exc())


        # Metrics iteration
        try:
            pf.scatterplot_var(
                var_file=metrics_best_path,
                plotfile=plot_iter_path / f"{basin_id}_metric_iteration.png",
                best_iteration=0,
                title="Metrics by Iteration"
            )
        except Exception as e:
            logger.warning(f"scatterplot_var (metric) failed: {e}")
            logger.info(traceback.format_exc())

        # Parameter iteration
        try:
            pf.scatterplot_var(
                var_file=metrics_best_path,
                plotfile=plot_iter_path / f"{basin_id}_param_iteration.png",
                best_iteration=0,
                title="Parameters by Iteration"
            )
        except Exception as e:
            logger.warning(f"scatterplot_var (param) failed: {e}")
            logger.info(traceback.format_exc())

        # Objective vs Metric plot
        try:
            pf.scatterplot_objfun_metric(
                var_file=metrics_best_path,
                plotfile=plot_iter_path / f"{basin_id}_metric_objfun.png",
                best_iteration=0,
                title="Obj Fun vs Metrics"
            )
        except Exception as e:
            logger.warning(f"scatterplot_objfun_metric failed: {e}")
            logger.info(traceback.format_exc())

        logger.info(f"[NoCalibModel] All calibration plots generated in Plot_Iteration.")



    def postprocess_single_validation_output(self, agent: 'Agent', valid_suffix=None):
        """
        Post-process validation output for NoCalibModel.

        This includes:
        -  Copying outputs from the run directory to Output_Valid
        - Computing metrics using metric_functions
    -     Generating plots via plot_functions
        """

        import shutil
        import copy
        import pandas as pd
        import csv
        from pathlib import Path
        from ngen.cal import metric_functions as mf
        from ngen.cal import plot_functions as pf
        from ngen.cal.search import _calc_metrics
        from types import SimpleNamespace
        from ngen.cal.plot_output import plot_valid_output

        workdir = Path(agent.job.workdir)
        basin_id = self.basinID
        output_valid_dir = workdir / "Output_Valid"
        output_valid_dir.mkdir(exist_ok=True)
        output_parent_path = Path(workdir).parent

        # Step 1: Get the fallback NEX CSV file
        matches = list(workdir.glob("nex-*_output.csv"))
        if not matches:
            raise FileNotFoundError(f"No NEX output CSV found in {workdir}")
        nex_file = matches[0]
        warnings.warn(f"Using fallback output file: {nex_file.name}", RuntimeWarning)

        # Step 2: Read the fallback file assuming no headers, manually assign
        df_raw = pd.read_csv(nex_file, header=None, names=["Time", "sim_flow"], parse_dates=["Time"])
        df_raw.set_index("Time", inplace=True)

        # Define file suffixes
        if not valid_suffix:
            valid_suffix = agent.run_name

        # Step 3: Save to Output_Iteration
        output_iter_file = output_parent_path / f"{basin_id}_output_{valid_suffix}.csv"
        df_raw.to_csv(output_iter_file)
        logger.info(f"[NoCalibModel] Wrote: {output_iter_file}")

        # Copy and rename output files
        for file in workdir.glob("*"):
            if file.suffix == ".csv" and ("cat-" in file.name or "nex-" in file.name):
                parts = file.name.split(".")[0].split("-")
                if len(parts) >= 2:
                    prefix = parts[0]  # cat or nex
                    catch_id = parts[1].split("_")[0]  # extract ID and remove existing suffix if present
                    new_name = f"{prefix}-{catch_id}_{valid_suffix}.csv"
                    shutil.move(file, output_valid_dir / new_name)

        # Locate renamed output files
        sim_files = list(output_valid_dir.glob(f"nex-*_{valid_suffix}.csv"))
        obs_path = Path(self.obsflow)

        try:
            obs_df = pd.read_csv(self.obsflow, parse_dates=["value_date"])
            obs_df = obs_df.rename(columns={"value_date": "Time", obs_df.columns[1]: "Observation"}).set_index("Time")

            # === Load simulation output file with header check ===
            sim_file = sim_files[0] #next(output_dir.glob(f"{basin_id}_output_valid_best.csv"), None)
            if not sim_file:
                print(f"[WARNING] Could not find {basin_id}_output_valid_best.csv")
                return

            with open(sim_file, 'r') as f:
                sample = f.read(1024)
                f.seek(0)
                has_header = csv.Sniffer().has_header(sample)

            if has_header:
                sim_df = pd.read_csv(sim_file, parse_dates=["Time"])
                if "Time" in sim_df.columns:
                    sim_df = sim_df.set_index("Time")
                sim_df.columns = ["Simulated"]
            else:
                sim_df = pd.read_csv(sim_file, header=None, names=["Time", "Simulated"], parse_dates=["Time"])
                sim_df = sim_df.set_index("Time")

            self.eval_params._eval_range = (
                pd.to_datetime(self.eval_params.evaluation_start),
                pd.to_datetime(self.eval_params.evaluation_stop)
            )
            self.eval_params._valid_eval_range = (
                pd.to_datetime(self.eval_params.valid_eval_start_time),
                pd.to_datetime(self.eval_params.valid_eval_end_time)
            )
            self.eval_params._full_eval_range = (
                pd.to_datetime(self.eval_params.full_eval_start_time),
                pd.to_datetime(self.eval_params.full_eval_end_time)
            )

            logger.info(f"self.eval_params : {self.eval_params}")

            output = sim_df
            observed = obs_df

            # Ensure column names for _calc_metrics expectations
            if isinstance(output, pd.Series):
                output = output.to_frame(name='sim_flow')
            else:
                output = output.rename(columns={output.columns[0]: 'sim_flow'})

            if isinstance(observed, pd.Series):
                observed = observed.to_frame(name='obs_flow')
            else:
                observed = observed.rename(columns={observed.columns[0]: 'obs_flow'})



            # Create dummy calibration object
            calibration_object = SimpleNamespace(
                output=output,
                observed=observed, #self.observed,
                station_name=basin_id,
                basinID=basin_id,
                evaluation_range=self.eval_params._eval_range,
                valid_evaluation_range=self.eval_params._valid_eval_range,
                full_evaluation_range=self.eval_params._full_eval_range,
                streamflow_name="sim_flow",
                threshold=self.eval_params.threshold
            )
            time_period = {'calib': calibration_object.evaluation_range, 'valid': calibration_object.valid_evaluation_range,
                           'full': calibration_object.full_evaluation_range}

            logger.info(f"time_period : {time_period}")

            # Compute metrics for each time period
            metrics = pd.DataFrame()
            for period_name, date_range in time_period.items():
                result = _calc_metrics(calibration_object.output, calibration_object.observed, date_range, calibration_object.threshold)
                row = {'run': valid_suffix, 'period': period_name, **result}
                metrics = pd.concat([metrics, pd.DataFrame([row])], ignore_index=True)

            # Save metrics to CSV
            metrics_path = Path(agent._valid_path) /  f"{basin_id}_metrics_{valid_suffix}.csv"
            metrics.to_csv(metrics_path, index=False)

            # df_all = pd.concat([obs_df, sim_df], axis=1).dropna()
        except Exception as e:
            logger.info(f"metrics calculation error : {e}")
            logger.info(traceback.format_exc())

        # Plottimg is not part of valid control workflow
        if valid_suffix != 'valid_best':
            logger.info(f"[NoCalibModel] Post-processing of single-run valid control output completed.")
            return

        # nwm_retro data
        try:

            if agent.nwmflow_file != '':
                if os.path.exists(agent.nwmflow_file):
                    logger.info(f'Read NWM retrospective streamflow simulation from: {agent.nwmflow_file}')
                    nwm = pd.read_csv(agent.nwmflow_file)
                    nwm.columns = ['value_date','sim_flow']
                    nwm['value_date'] = pd.DatetimeIndex(nwm['value_date'])
                    print(nwm['value_date'])
                    agent.nwmflow = nwm.set_index('value_date')
                else:
                    logger.error(f'File does not exist: {agent.nwmflow_file}')
            else:
                agent.nwmflow = None
                agent.nwmflow = self.nwmflow
            print(f'agent.nwmflow : {agent.nwmflow}')

            df_nwm_metrics = pd.DataFrame()

            observed = agent.nwmflow

            if isinstance(observed, pd.Series):
                observed = observed.to_frame(name='obs_flow')
            else:
                observed = observed.rename(columns={observed.columns[0]: 'obs_flow'})

            '''
            nwmflow = None
            if agent.nwmflow is not None:
                if isinstance(agent.nwmflow, pd.Series):
                    nwmflow = agent.nwmflow.to_frame(name='obs_flow')
            else:
                nwmflow = agent.nwmflow.rename(columns={agent.nwmflow.columns[0]: 'obs_flow'})
            '''
            for period_name, date_range in time_period.items():
                result = _calc_metrics(calibration_object.output, observed, date_range, calibration_object.threshold)
                nwm_row = {'run': 'nwm_retro', 'period': period_name, **result}  # or modify result if needed for NWM
                df_nwm_metrics = pd.concat([df_nwm_metrics, pd.DataFrame([nwm_row])], ignore_index=True)
            nwm_metrics_path = Path(agent._valid_path) /  f"{basin_id}_metrics_nwm_retro.csv"
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
                combined_df = combined_df.drop(columns=[c for c in drop_cols if c in combined_df.columns])

                # Reorder for consistency: objFunVal, CORR, others...
                #front = ["objFunVal", "CORR"]
                #rest = [c for c in combined_df.columns if c not in front]
                #combined_df = combined_df[front + rest]

                combined_path = Path(agent.valid_path) / f"{basin_id}_metrics_valid_run.csv"
                combined_df.to_csv(combined_path, index=False)
                logger.info(f"Saved combined validation metrics to {combined_path}")
        except Exception as e:
            logger.warning(f"Failed to create combined metrics_valid_run.csv: {e}")
            logger.info(traceback.format_exc())

        try:

            # Fix df_precip formatting to add a 'Time' column
            df_precip_fixed = agent.df_precip.copy()
            df_precip_fixed = df_precip_fixed.reset_index().rename(columns={"index": "Time"})

            # Clone the agent with all fields + override df_precip
            agent_fixed = SimpleNamespace(**vars(agent), df_precip=df_precip_fixed, valid_path=agent.valid_path, valid_path_plot=agent.valid_path_plot)
           

            # Call plot_valid_output to produce all standard plots

            logger.info("\nCalling plot_valid_output")
            plot_valid_output(
                calibration_object=calibration_object,
                agent=agent_fixed,
                runs=runs,
                time_period=time_period
            )
        except Exception as e:
            logger.warning(f"plot_valid_output failed: {e}")
            logger.info(traceback.format_exc())

        logger.info("[NoCalibModel] All validation plots generated in Plot_Valid.")


        # Create merged DataFrame for plotting
        obs_df = pd.read_csv(obs_path, index_col=0, parse_dates=True)
        obs_df = obs_df.rename(columns={obs_df.columns[0]: 'Observation'})
        sim_df = pd.read_csv(output_iter_file, index_col=0, parse_dates=True)
        sim_df = sim_df.rename(columns={sim_df.columns[0]: 'valid_best'})
        nwm_df = self.df_nwm

        # Ensure all indices are datetime and aligned
        obs_df.index = pd.to_datetime(obs_df.index)
        sim_df.index = pd.to_datetime(sim_df.index)
        nwm_df.index = pd.to_datetime(nwm_df.index)

        merged_df = pd.concat([obs_df, sim_df, nwm_df], axis=1).dropna()
        merged_df.index.name = "Time"

        # For plotting, keep a deep copy and reset index
        # Sort and reorder DataFrame columns explicitly

        merged_df = merged_df[["Observation", "nwm_retro", "valid_best"]]


        # Refactoring so that they all are visible in the plot
        max_obs = merged_df['Observation'].max()
        for col in merged_df.columns:
            if col not in ['Time', 'Observation', 'nwm_retro']:
                factor = max_obs / merged_df[col].max()
                merged_df[col] *= factor


        merged_df.index.name = "Time"
        df_plot = merged_df.iloc[24:].copy().reset_index()

        try:
            pf.plot_streamflow(
                df=copy.deepcopy(df_plot),
                plotfile=Path(agent._valid_path_plot) / f"{basin_id}_hydrograph_valid_run_1.png",
                title=f"Hydrograph (Valid Best)\n{basin_id}"
            )
        except Exception as e:
            logger.info(df_plot)
            logger.warning(f"plot_streamflow_valid : {e}")
            logger.info(traceback.format_exc())


    def unused_valid_plot_functions_delete(self, agent):
        '''
        This is old code that will be deleted
        '''

        # Create merged DataFrame for plotting
        obs_df = pd.read_csv(obs_path, index_col=0, parse_dates=True)
        obs_df = obs_df.rename(columns={obs_df.columns[0]: 'Observation'})
        sim_df = pd.read_csv(output_iter_file, index_col=0, parse_dates=True)
        sim_df = sim_df.rename(columns={sim_df.columns[0]: 'valid_best'})
        nwm_df = self.df_nwm

        # Ensure all indices are datetime and aligned
        obs_df.index = pd.to_datetime(obs_df.index)
        sim_df.index = pd.to_datetime(sim_df.index)
        nwm_df.index = pd.to_datetime(nwm_df.index)

        merged_df = pd.concat([obs_df, sim_df, nwm_df], axis=1).dropna()
        merged_df.index.name = "Time"

        # For plotting, keep a deep copy and reset index
        # Sort and reorder DataFrame columns explicitly

        merged_df = merged_df[["Observation", "nwm_retro", "valid_best"]]
        merged_df.index.name = "Time"
        df_plot = merged_df.iloc[24:].copy().reset_index()
        
        try:
            pf.plot_streamflow(
                df=copy.deepcopy(df_plot),
                plotfile=plot_valid_dir / f"{basin_id}_hydrograph_valid_run.png",
                title=f"Hydrograph (Valid Best)\n{basin_id}"
            )
        except Exception as e:
            logger.info(df_fdc)
            logger.warning(f"plot_streamflow_valid : {e}")
            logger.info(traceback.format_exc())

        try:

            df_fdc = merged_df.iloc[24:].copy()
            df_fdc.index = pd.to_datetime(df_fdc.index) 
            df_fdc = df_fdc.reset_index() 
            
            pf.plot_fdc_valid(
                df=copy.deepcopy(df_fdc),
                plotfile=plot_valid_dir / f"{basin_id}_fdc_valid_run.png",
                title=f"Flow Duration Curve (Valid Best)",
                time_period={
                    "calib": (df_fdc.index.min(), df_fdc.index.max()),
                    "valid": (df_fdc.index.min(), df_fdc.index.max()),
                    "full": (df_fdc.index.min(), df_fdc.index.max()),
                }
            )
        except Exception as e:
            logger.info(df_fdc)
            logger.warning(f"plot_fdc_valid : {e}")
            logger.info(traceback.format_exc())


        try:
            df_precip = self.df_precip.reset_index()
            #df_precip.rename(columns={'Precip(mm)': 'RAINRATE'}, inplace=True)
            pf.plot_streamflow_precipitation(
                df=copy.deepcopy(df_plot),
                dfp=df_precip,
                plotfile=plot_valid_dir / f"{basin_id}_streamflow_precip_valid_run.png",
                title=f"Streamflow + Precipitation (Valid Best)"
            )
        except Exception as e:
            
            logger.warning(f"Precipitation plot skipped: {e}")
            logger.info(traceback.format_exc())


        metrics_control_path = output_parent_path /  f"{basin_id}_metrics_valid_control.csv"
        metrics_best_path = output_parent_path /  f"{basin_id}_metrics_valid_best.csv"
        df_control = pd.read_csv(metrics_control_path)
        df_best = pd.read_csv(metrics_best_path)
        df_nwm = pd.read_csv(obs_path)

        df_combined = pd.concat([df_control, df_best, df_nwm], axis=0)
        df_combined.to_csv("01123000_metrics_combined.csv", index=False)

      
        try:
            pf.barplot_metric(
                df=df_combined,
                plotfile=plot_valid_dir / f"{basin_id}_barplot_metrics_valid_run.png",
                title=f"Metrics for Valid Best Run"
            )
        except Exception as e:
            logger.info(f"metrics df : {metrics_df}")
            logger.warning(e)

        logger.info("[NoCalibModel] All validation plots generated in Plot_Valid.")


    def get_obsflow(self) -> pd.DataFrame:
        print(f'self.obsflow : {self.obsflow}')
        df = pd.read_csv(self.obsflow, index_col=0, parse_dates=True)
        if 'Time' in df.columns:
            df.set_index("Time", inplace=True)
        return df

    def get_args(self) -> str:
        return f"{self.catchments} all {self.nexus} all {self.realization}"

    def update_config(self, i: int, params: pd.DataFrame, id=None, path: Path = Path(".")):
        # No-op for single-run models
        pass

    def resolve_paths(self):
        self.realization = self.realization.resolve()
        self.catchments = self.catchments.resolve()
        self.nexus = self.nexus.resolve()
        self.obsflow = self.obsflow.resolve()
        self.nwmflow = self.nwmflow.resolve()

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
    def threshold(self):
        return self.eval_params.threshold

    @property
    def realization_file(self) -> Path:
        return self.realization

    @property
    def output(self) -> pd.DataFrame:
        if not self._output_iter_file or not self._output_iter_file.exists():
            raise FileNotFoundError(f"No simulation output file found at: {self._output_iter_file}")
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
            from ngen.cal.plot_output import plot_metric, plot_obj_fun, plot_streamflow, plot_scatterplot, plot_fdc
            plot_metric(agent)
            plot_obj_fun(agent)
            plot_streamflow(agent, df, self.observed, basinID, plot_iter_path, title="Streamflow")
            plot_scatterplot(agent, df, self.observed, basinID, plot_iter_path)
            plot_fdc(agent, df, self.observed, basinID, plot_iter_path)
        
    @property
    def df_nwm(self):
        if not hasattr(self, "nwmflow"):
            raise AttributeError("No NWM flow file configured.")
        path = Path(self.nwmflow)
        if not path.exists():
            raise FileNotFoundError(f"NWM flow file not found: {path}")
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df = df.rename(columns={df.columns[0]: 'nwm_retro'})
        return df

    @property
    def df_precip(self):
        """
        Reads forcing precipitation data based on realization JSON.
        Mimics logic from NgenBase in ngen.py.
        """
        from functools import reduce
        import json
        from datetime import datetime
        
        realization_path = self.realization
        if not realization_path.exists():
            raise FileNotFoundError(f"Realization file not found: {realization_path}")

        print(realization_path)

        with open(realization_path, 'r') as f:
            realization = json.load(f)

        print(realization.get("global", {}).get("forcing", {}))
        #forcing_cfg = realization.get('global_config', {}).get('forcing', {})
        forcing_cfg = realization.get("global", {}).get("forcing", {})
        print(f"\nforcing_cfg : {forcing_cfg}")

        forcing_path = forcing_cfg.get('path')
        file_pattern = forcing_cfg.get('file_pattern', '*.csv')

        # start_date = datetime.strftime(realization.get("time").get("start_time"), '%Y-%m-%d %H:%M:%S')
        # end_date = datetime.strftime(realization.get("time").get("end_time"), '%Y-%m-%d %H:%M:%S')

        start_date = realization.get("time").get("start_time")
        end_date = realization.get("time").get("end_time")


        flst = []
        for ffile in glob.glob(os.path.join(forcing_path, '*.csv')):
            fdata = pd.read_csv(ffile)
            fdata_copy = fdata.copy()[['Time','RAINRATE']]
            fdata_copy['Time'] = pd.DatetimeIndex(fdata_copy['Time'])
            fdata_copy.set_index('Time', inplace=True)
            fdata_copy = fdata_copy.loc[start_date:end_date]
            flst.append(fdata_copy)

        if not flst:
            raise ValueError("No valid RAINRATE data found in forcing files.")

        suffixes=[f"_{i}" for i in range(len(flst))]
        flst=[flst[i].add_suffix(suffixes[i]) for i in range(len(flst))]
        df_precip = reduce(lambda left, right: pd.merge(left, right, left_index=True, right_index=True), flst)
        dfp = df_precip.sum(axis=1)*3600
        dfp.name = 'RAINRATE'
        # self._precip = dfp.reset_index()

        df_merged = reduce(lambda x, y: pd.merge(x, y, left_index=True, right_index=True, how='outer'), flst).fillna(0)
        df_precip = df_merged.sum(axis=1) * 3600.0  # Convert mm/hr to mm
        #df_precip = df_precip.to_frame(name="Precip(mm)")
        df_precip = df_precip.to_frame(name="RAINRATE")
        df_precip.index.name = "Time"
        return df_precip


    def write_cost_iter_file(self, i, path):
        # No-op for single-run NoCalibModel
        pass

Model.update_forward_refs()
