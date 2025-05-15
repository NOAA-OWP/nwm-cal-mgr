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
    evaluation_range: Optional[List[datetime]] = None
    metrics: Optional[Dict[str, float]] = None

    def execute_model(self):
        """
        Execute the model run for single-execution validation.
        This mirrors the interface of calibrated models.
        """
        logger.info("[NoCalibModel] Executing model (validation run)")
        self.run(self.get_args())

    def postprocess_single_calibration_output_new(self, output_dir, basin_id, output_iter_path):
        from .search import _calc_metrics as calculate_all_metrics

        if isinstance(output_dir, str):
            output_dir = Path(output_dir)
        if isinstance(output_iter_path, str):
            output_iter_path = Path(output_iter_path)

        ngen_output_dir = output_dir  # This is the worker root dir
        nex_files = sorted(ngen_output_dir.glob(f"**/nex-*_output.csv"))
        cat_files = sorted(ngen_output_dir.glob(f"**/cat-*.csv"))

        if not nex_files:
            raise FileNotFoundError(f"No nex output found in {ngen_output_dir}")

        output_iter_path.mkdir(parents=True, exist_ok=True)
        output_calib_path = ngen_output_dir / "Output_Calib"
        output_calib_path.mkdir(parents=True, exist_ok=True)

        for f in nex_files + cat_files:
            shutil.copy2(f, output_calib_path)

        df_raw = pd.read_csv(nex_files[0], index_col=0, parse_dates=True)
        df_raw.rename(columns={df_raw.columns[0]: "sim_flow"}, inplace=True)

        obs = pd.read_csv(self.obsflow, index_col=0, parse_dates=True)
        obs.rename(columns={obs.columns[0]: "obs_flow"}, inplace=True)

        df = pd.concat([obs, df_raw], axis=1).dropna()
        logger.info(f"eval_range : {self.evaluation_range}")
        logger.info(f"eval_range : ({self.eval_params.evaluation_start}, {self.eval_params.evaluation_stop})")
        logger.info(df.head())

        self.metrics = calculate_all_metrics(df["obs_flow"], df["sim_flow"], self.eval_params)
        logger.info(f"self.metrics : {self.metrics}")

        df_metrics = pd.DataFrame.from_dict(self.metrics, orient='index', columns=["metric"]).T
        df_metrics.index = [0]
        df_metrics["run_type"] = "calib"
        df_metrics["iteration"] = 0

        df_metrics.to_csv(output_iter_path / f"{basin_id}_output_iteration_0000.csv")

        plot_iter_path = ngen_output_dir / "Plot_Iteration"
        plot_iter_path.mkdir(parents=True, exist_ok=True)
        df_plot = df.reset_index().rename(columns={"index": "Time"})

        plot_streamflow(df_plot, plot_iter_path / f"{basin_id}_hydrograph_iteration.png")
        plot_fdc(df_plot, plot_iter_path / f"{basin_id}_fdc_iteration.png")
        plot_scatter(df_plot, plot_iter_path / f"{basin_id}_scatterplot_streamflow_iteration.png")
        plot_obj_fun(df_metrics, plot_iter_path / f"{basin_id}_objfun_iteration.png")

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

    def create_validation_configs_last(self, agent):
        """
        For NoCalibModel, generate dummy 'valid_control' and 'valid_best' config YAMLs
        and their corresponding realization files, so validation workflow runs as expected.
        """
        import yaml
        from copy import deepcopy
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

            # Load original YAML
            with open(input_yaml_path, "r") as f:
                config = yaml.safe_load(f)

            # Update general section
            config["general"]["name"] = tag
            config["general"]["yaml_file"] = str(yaml_out)
            config["model"]["realization"] = str(realization_out)

            # Optional: strip out params if they don't exist
            config["model"].pop("params", None)

            # Write new YAML
            with open(yaml_out, "w") as f:
                yaml.dump(config, f)

            logger.info(f"Config file for {tag} created at {yaml_out}")

    def postprocess_single_calibration_output(self, workdir: Path, basin_id: str, output_iter_path: Path):
        import shutil
        import pandas as pd
        import logging
        from ngen.cal import metric_functions as mf
        from ngen.cal import plot_functions as pf
        from .plot_output import plot_calib_output


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
        output_file = output_iter_path / f"{basin_id}_output_iteration_0000.csv"
        df_raw.to_csv(output_file)
        logger.info(f"[NoCalibModel] Wrote: {output_file}")

        self._output_iter_file = output_file
        self._output_iter_file = str(output_iter_path / f"{basin_id}_output_iteration_0000.csv")

        logger.info(f"[NoCalibModel] Wrote: {output_file}")

        # Step 4: Copy cat-* and nex-*output.csv to Output_Calib
        output_calib_path = workdir / "Output_Calib"
        output_calib_path.mkdir(parents=True, exist_ok=True)

        for file in workdir.glob("cat-*.csv"):
            shutil.move(file, output_calib_path)
        for file in workdir.glob("nex-*_output.csv"):
            shutil.move(file, output_calib_path)
        
        # Step 5: Compute and store metrics
        obs = self.get_obsflow()
        df = pd.concat([df_raw["sim_flow"], obs], axis=1).dropna()
        df.columns = ["sim_flow", "obs_flow"]
        df = df.loc[self.evaluation_range[0]:self.evaluation_range[1]]
        
        logger.info(f"eval_range : {self.evaluation_range}")
        logger.info(f"{df.head()}")

        # Compute metrics
        self.metrics = calculate_all_metrics(
            df["obs_flow"], df["sim_flow"], self.evaluation_range, self.threshold
        )

        logger.info(f"self.metrics : {self.metrics}")
        logger.info(f"self.eval_params.objective : {self.eval_params.objective}")

        score = self.metrics.get(self.eval_params.objective, None)
        if score is None:
            score = self.metrics.get(self.eval_params.objective.upper(), None)
            if score is None:
                raise ValueError(f"Objective function metric '{self.eval_params.objective}' not found in metrics")

        # Write metrics to CSV
        metrics_path = output_iter_path / f"{basin_id}_metrics_single_run.csv"
        pd.DataFrame([self.metrics]).to_csv(metrics_path, index=False)

        # Generate plots
        plot_iter_path = workdir / "Plot_Iteration"
        plot_iter_path.mkdir(parents=True, exist_ok=True)

        title = f"Single-Run Evaluation - {basin_id}"

        # Hydrograph
        df_hydro = df.copy()
        df_hydro["Time"] = df_hydro.index
        df_hydro = df_hydro[["Time", "obs_flow", "sim_flow"]]
        pf.plot_streamflow(df_hydro, plot_iter_path / f"{basin_id}_hydrograph_iterations.png", title)

        # Flow Duration Curve
        df_fdc = df.rename(columns={"obs_flow": "Observation", "sim_flow": "SingleRun"})
        pf.plot_fdc_calib(df_fdc, plot_iter_path / f"{basin_id}_fdc_iterations.png", title)

        # Scatterplot
        df_scat = df.rename(columns={"obs_flow": "Observation", "sim_flow": "SingleRun"})
        df_scat["Time"] = df.index
        pf.scatterplot_streamflow(df_scat, plot_iter_path / f"{basin_id}_scatter_iterations.png", title)

        # Prepare DataFrame for plotting
        df_metrics = pd.DataFrame(self.metrics, index=[0])
        df_metrics["iteration"] = 0
        df_metrics.set_index("iteration", inplace=True)
        pf.barplot_metric(df_metrics, plot_iter_path / f"{basin_id}_barplot_metrics_iterations.png","braplot_metrics_test")

        logger.info("[NoCalibModel] Generated metric and objective function plots.")
        logger.info(f"[NoCalibModel] Post-processing of single-run output completed.")


    def postprocess_single_validation_output(self, agent: 'Agent'):
        """
        Post-process validation output for NoCalibModel.

        This includes:
        -  Copying outputs from the run directory to Output_Valid
        - Renaming them with '_valid_best' suffix
        - Computing metrics using metric_functions
    -     Generating plots via plot_functions
        """

        import os
        import shutil
        import copy
        import pandas as pd
        import traceback
        from pathlib import Path
        from ngen.cal import metric_functions as mf
        from ngen.cal import plot_functions as pf

        workdir = Path(agent.job.workdir)
        basin_id = self.basinID
        output_valid_dir = workdir / "Output_Valid"
        output_valid_dir.mkdir(exist_ok=True)


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
        best_output_file = workdir / f"{basin_id}_output_valid_best.csv"
        best_nex_output_file = workdir / f"nex-{basin_id}_output_valid_best.csv"
        best_nex_output_valid_file = output_valid_dir / f"nex-{basin_id}_output_valid_best.csv"
        df_raw.to_csv(best_output_file)
        df_raw.to_csv(best_nex_output_file)
        df_raw.to_csv(best_nex_output_valid_file)
        logger.info(f"[NoCalibModel] Wrote: {best_output_file}")
        logger.info(f"[NoCalibModel] Wrote: {best_nex_output_file}")
        logger.info(f"[NoCalibModel] Wrote: {best_nex_output_valid_file}")


        # Define file suffixes
        valid_suffix = "valid_best"

        # nex-01123000_output_valid_best.csv

        # Copy and rename output files
        output_iter_path = workdir / "Output"
        for file in workdir.glob("*"):
            if file.suffix == ".csv" and ("cat-" in file.name or "nex-" in file.name):
                parts = file.name.split(".")[0].split("-")
                if len(parts) >= 2:
                    prefix = parts[0]  # cat or nex
                    catch_id = parts[1].split("_")[0]  # extract ID and remove existing suffix if present
                    new_name = f"{prefix}-{catch_id}_{valid_suffix}.csv"
                    shutil.copy(file, output_valid_dir / new_name)

        # Locate renamed output files
        sim_files = list(output_valid_dir.glob(f"nex-*_{valid_suffix}.csv"))
        obs_path = Path(self.obsflow)

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

        # Save metrics
        metrics_df = pd.DataFrame(all_metrics)
        metrics_path = output_valid_dir / f"validation_metrics_{valid_suffix}.csv"
        metrics_path_workdir = workdir / f"validation_metrics_{valid_suffix}.csv"
        metrics_df.to_csv(metrics_path, index=False)
        metrics_df.to_csv(metrics_path_workdir, index=False)
        logger.info(f"[NoCalibModel] Metrics written: {metrics_path}")

        plot_valid_dir = Path(agent.job.workdir) / "Plot_Valid"
        plot_valid_dir.mkdir(exist_ok=True)

        try:
            renamed_output = plot_valid_dir / f"{basin_id}_output_valid_best.csv"
            shutil.copy(output_valid_dir / f"nex-{basin_id}_output_valid_best.csv", renamed_output)
            renamed_metrics = plot_valid_dir / f"{basin_id}_metrics_valid_best.csv"
            shutil.copy(metrics_path, renamed_metrics)
        except Exception as e:
            logger.error(f"Error copying output/metrics to Plot_Valid: {e}")

        # Create merged DataFrame for plotting
        obs_df = pd.read_csv(obs_path, index_col=0, parse_dates=True)
        obs_df = obs_df.rename(columns={obs_df.columns[0]: 'Observation'})
        sim_df = pd.read_csv(renamed_output, index_col=0, parse_dates=True)
        sim_df = sim_df.rename(columns={sim_df.columns[0]: 'valid_best'})
        nwm_df = self.df_nwm
        merged_df = pd.concat([nwm_df, obs_df, sim_df], axis=1).dropna()
        merged_df.index.name = "Time"
        df_plot = merged_df.iloc[24:].copy().reset_index()

        pf.plot_streamflow(
            df=copy.deepcopy(df_plot),
            plotfile=plot_valid_dir / f"{basin_id}_hydrograph_valid_run.png",
            title=f"Hydrograph (Valid Best)\n{basin_id}"
        )

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
            df_precip = self.df_precip
            df_precip = df_precip.reset_index()
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
            metrics_df = pd.read_csv(renamed_metrics)
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
