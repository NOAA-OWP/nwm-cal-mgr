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
        metrics["catchment_id"] = basin_id
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
            metrics_df["run_type"] = "calib"
            metrics_df["basin_id"] = basin_id
            metrics_df["iteration"] = 0

            logger.info(f"Calibration metrics 1: \n{metrics_df}")

            '''

            obs_file = Path(self.obsflow)
            df_obs = pd.read_csv(obs_file, index_col=0, parse_dates=True)
            df_obs.columns = ["Observation"]

            df_obs, df_sim = df_obs.align(df_sim["Simulated"], join="inner")

            if df_obs.empty or df_sim.empty:
                raise ValueError("No overlapping dates found between sim and obs data.")

            metrics = mf.calculate_all_metrics(df_obs, df_sim)
            metrics["catchment_id"] = basin_id
            metrics["iteration"] = 0
            df_metrics = pd.DataFrame([metrics])
            df_metrics.insert(0, "run_type", "calib_best")
            df_metrics.insert(1, "basin_id", basin_id)
            '''

            metrics_path = workdir / f"{basin_id}_metrics_iteration.csv"
            metrics_df.to_csv(metrics_path, index=False)

            # Plot metrics
            from ngen.cal.plot_functions import barplot_metric
            barplot_metric(
                df=metrics_df,
                plotfile=plot_iter_path / f"{basin_id}_barplot_metrics_iteration.png",
                title="Calibration Metrics"
            )
        except Exception as e:
            logger.warning(f"Metrics or plot failed: {e}")
            logger.info(traceback.format_exc())



        # Cost function
        try:
            cost_dir = output_dir / "Output_Calib"
            cost_dir.mkdir(exist_ok=True)
            cost_path = cost_dir / f"{basin_id}_output_cost.csv"
            obj_value = metrics[self.eval_params.objective.upper()]
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
            # df_scatter = df_all.copy()
            # df_scatter = df_scatter.rename(columns={"Observation": "Observation", "best": "Simulated"})
            # df_scatter = df_scatter.reset_index()  # Makes 'Time' a column
            # df_scatter = df_all.rename(columns={"Best Run": "Simulated"})


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



        # Barplot metrics
        try:
            pf.barplot_metric(
                df=metrics_df,
                plotfile=plot_iter_path / f"{basin_id}_barplot_metrics_iteration.png"
            )
        except Exception as e:
            logger.warning(f"barplot_metric failed: {e}")
            logger.info(traceback.format_exc())

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


        # Metrics Barplot
        try:
            # metrics_df.insert(0, "run_type", "calib_best")
            # metrics_df.insert(1, "basin_id", basin_id)
            pf.barplot_metric(
                df=metrics_df,
                plotfile=plot_iter_path / f"{basin_id}_barplot_metrics_iteration.png",
                title="Metrics for Calibration Best Run"
            )
        except Exception as e:
            logger.warning(f"barplot_metrics : {e}")
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
        - Renaming them with '_valid_best' suffix
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
            # Metric calculation
            sim_file = sim_files[0]
            obs_file = Path(self.obsflow)
            y_true = pd.read_csv(obs_file, index_col=0, parse_dates=True).iloc[:, 0]
            y_pred = pd.read_csv(sim_file, index_col=0, parse_dates=True).iloc[:, 0]
            y_true, y_pred = y_true.align(y_pred, join="inner")
            metrics = mf.calculate_all_metrics(y_true, y_pred)
            metrics["catchment_id"] = basin_id
            metrics["iteration"] = 0
            metrics["run_type"] = valid_suffix
            metrics["basin_id"] = basin_id

            metrics_df = pd.DataFrame([metrics])
            metrics_best_path = workdir / f"{basin_id}_metrics_iteration.csv"
            metrics_df.to_csv(metrics_best_path, index=False)
            # shutil.copy(metrics_path, plot_iter_path / metrics_path.name)
            logger.info(f"\nValidation metrics -1 : \n{metrics_df}")
            metrics_file = output_parent_path / f"{basin_id}_metrics_{run_type}.csv"
            metrics_df.to_csv(metrics_file, index=False)

            print("---Plotting Barplot of Validation Metrics---")
            barplot_metric(
                df=metrics_df,
                metric_file=metrics_file,
                plotfile=workdir / f"{basin_id}_barplot_metrics_{run_type}_1.png",
                allcols=metrics_df.columns[2:].tolist(),
                labels=[run_type]
            )

        except Exception as e:
            logger.info(f"metrics calculation error : {e}")
            logger.info(traceback.format_exc())


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

            df_all = pd.concat([obs_df, sim_df], axis=1).dropna()

            metrics = mf.calculate_all_metrics(df_all["Observation"], df_all["Simulated"])
            metrics_df = pd.DataFrame([metrics])
            metrics_df["run_type"] = valid_suffix
            metrics_df["basin_id"] = basin_id
            logger.info(f"\nValidation metrics 0 : \n{metrics_df}")
            metrics_file = workdir / f"{basin_id}_metrics_{run_type}_1.csv"
            metrics_df.to_csv(metrics_file, index=False)

            print("---Plotting Barplot of Validation Metrics---")
            barplot_metric(
                df=metrics_df,
                metric_file=metrics_file,
                plotfile=workdir / f"{basin_id}_barplot_metrics_{run_type}_2ng",
                allcols=metrics_df.columns[2:].tolist(),
                labels=[run_type]
            )

        except Exception as e:
            logger.info(f"metrics calculation error : {e}")
            logger.info(traceback.format_exc())

        sim_df = pd.read_csv(sim_files[0], index_col=0, parse_dates=True)
        obs_df = pd.read_csv(obs_path, index_col=0, parse_dates=True)

        # Make sure we select the correct column
        if sim_df.shape[1] != 1:
            logger.warning(f"Unexpected sim_df columns: {sim_df.columns}")
        sim_series = sim_df.iloc[:, 0]

        if obs_df.shape[1] != 1:
            logger.warning(f"Unexpected obs_df columns: {obs_df.columns}")
        obs_series = obs_df.iloc[:, 0]

        # Align and check overlap
        obs_series, sim_series = obs_series.align(sim_series, join="inner")

        if len(sim_series) < 2:
            logger.warning(f"No overlapping data after align: obs({len(obs_series)}), sim({len(sim_series)})")

        metrics = mf.calculate_all_metrics(obs_series, sim_series)
        logger.info("\nValidation Metrics 1:")
        logger.info(metrics)



        # Merge and compute metrics for all files
        all_metrics = []
        for sim_file in sim_files:
            catch_id = sim_file.name.split("-")[1].split("_")[0]
            obs_file = obs_path  # assumed to be a single CSV for now
            try:
                sim_df = pd.read_csv(sim_file, index_col=0, parse_dates=True).iloc[:, 0]
                obs_df = pd.read_csv(obs_file, index_col=0, parse_dates=True).iloc[:, 0]
                obs_df, sim_df = obs_df.align(sim_df, join="inner")
                metrics = mf.calculate_all_metrics(obs_df, sim_df)
                metrics["catchment_id"] = catch_id
                all_metrics.append(metrics)
            except Exception as e:
                print(f"[NoCalibModel] Failed to compute metrics for {sim_file}: {e}")
                logger.info(traceback.format_exc())


        # Save metrics
        metrics_df = pd.DataFrame(all_metrics)
        metrics_df.insert(0, "run_type", "valid_best")
        metrics_df.insert(1, "basin_id", basin_id)
        logger.info(f"Validation metrics 2 : \n{metrics_df}")

        metrics_path_parent = output_parent_path / f"validation_metrics_{valid_suffix}.csv"
        metrics_df.to_csv(metrics_path_parent, index=False)
        logger.info(f"[NoCalibModel] Metrics written: {metrics_path_parent}")


        # Plottimg is not part of valid control workflow
        if valid_suffix != 'valid_best':
            logger.info(f"[NoCalibModel] Post-processing of single-run valid control output completed.")
            return


        plot_valid_dir = Path(output_parent_path) / "Plot_Valid"
        plot_valid_dir.mkdir(exist_ok=True)


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

        try:
            metrics_df = pd.read_csv(metrics_path_parent)
            metrics_df.insert(0, "run_type", "valid_best")
            metrics_df.insert(1, "basin_id", basin_id)
            pf.barplot_metric(
                df=metrics_df,
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
