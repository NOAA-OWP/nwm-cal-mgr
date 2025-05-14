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

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)



from .model import BaseModel
#from .metrics import calculate_all_metrics
from . import plot_output

#logger = logging.getLogger("NGEN_CAL")


# ... [existing imports and code above remain unchanged] ...

class NoCalibModelNew(ModelExec):
    type: Literal["nocalib"] = "nocalib"
    strategy: Optional[str] = Field(default="uniform")

    realization: Path
    catchments: Path
    nexus: Path
    obsflow: Path

    objective_score: Optional[float] = None
    _output_iter_file: Path = PrivateAttr(default=None)
    evaluation_range: Optional[List[datetime]] = None
    metrics: Optional[Dict[str, float]] = None

    def update_config(self, iteration, params_df, model_id):
        """
        No-op for NoCalibModel since there are no calibratable parameters.
        This is required to fulfill the abstract method from the base class.
        """
        logger.info(f"[NoCalibModel] update_config() called at iteration {iteration} — no-op.")

    def execute_model(self):
        """
        Execute the model run for single-execution (no calibration) mode.
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

    def postprocess_single_validation_output(self, agent: 'Agent'):
        """
        Post-process the results of a single-run model execution for validation.
        Collect output files, compute metrics, and generate validation plots.
        """
        logger.info("[NoCalibModel] Post-processing validation run (Single Exec)")

        import shutil
        import pandas as pd
        from .search import _calc_metrics as calculate_all_metrics
        from .plot_output import hydrograph_valid, fdc_plot_valid, barplot_metrics_valid, streamflow_precip_valid

        basin_id = self.basinID
        output_dir = Path(agent.valid_path)
        plot_dir = Path(agent.valid_path_plot)
        output_dir.mkdir(parents=True, exist_ok=True)
        plot_dir.mkdir(parents=True, exist_ok=True)

        # Locate the model output (Ngen NEX output CSV) from the worker directory
        nex_files = sorted(Path().glob("nex-*_output.csv"))
        if not nex_files:
            raise FileNotFoundError(f"No model output file found for basin {basin_id} in {agent.job.workdir}")
        sim_file = nex_files[0]
        logger.info(f"[NoCalibModel] Using simulation output file: {sim_file.name}")

        # Read simulation and observation data
        df_sim = pd.read_csv(sim_file, index_col=0, parse_dates=True)
        # Ensure simulation column is named consistently
        df_sim.rename(columns={df_sim.columns[0]: "sim_flow"}, inplace=True)
        df_obs = pd.read_csv(self.obsflow, index_col=0, parse_dates=True)
        df_obs.rename(columns={df_obs.columns[0]: "obs_flow"}, inplace=True)
        # Align and combine simulation and observation data
        df = pd.concat([df_sim, df_obs], axis=1).dropna()

        # Apply evaluation time window for validation if specified
        if self.eval_params.valid_eval_start_time and self.eval_params.valid_eval_end_time:
            df = df.loc[self.eval_params.valid_eval_start_time : self.eval_params.valid_eval_end_time]
        elif self.eval_params.valid_start_time and self.eval_params.valid_end_time:
            df = df.loc[self.eval_params.valid_start_time : self.eval_params.valid_end_time]
        elif self.eval_params.evaluation_start and self.eval_params.evaluation_stop:
            df = df.loc[self.eval_params.evaluation_start : self.eval_params.evaluation_stop]

        # Compute performance metrics for the validation period
        metrics = calculate_all_metrics(df["sim_flow"], df["obs_flow"], self.eval_params.threshold)
        self.metrics = metrics  # store metrics in the model object
        df_metrics = pd.DataFrame([metrics])

        # Save metrics and output to Validation output directory
        metrics_file = output_dir / f"{basin_id}_metrics_valid_control.csv"
        df_metrics.to_csv(metrics_file, index=False)
        logger.info(f"[NoCalibModel] Metrics written: {metrics_file}")
        output_file = output_dir / f"{basin_id}_output_valid_control.csv"
        shutil.copy2(sim_file, output_file)
        logger.info(f"[NoCalibModel] Output time series saved: {output_file}")

        # Generate validation plots
        hydrograph_valid(df, plot_dir, basin_id, label="Valid_Run")
        fdc_plot_valid(df, plot_dir, basin_id, label="Valid_Run")
        barplot_metrics_valid(df_metrics, plot_dir, basin_id, label="Valid_Run")
        if hasattr(self, "precip_forcing") and getattr(self, "precip_forcing") and Path(self.precip_forcing).exists():
            # If precipitation forcing data is available, include precip vs streamflow plot
            streamflow_precip_valid(df, self.precip_forcing, plot_dir, basin_id, label="Valid_Run")

        logger.info("[NoCalibModel] Validation post-processing complete.")

    # ... [other methods remain unchanged or as defined above] ...

    def write_iteration_outputs(self, agent, metrics: dict, obj_score: float):
        """
        Save final single-run outputs (metrics, logs, dummy params) for calibration stage
        and prepare for validation. This is called at the end of a NoCalibModel "calibration" execution.
        """
        i = 0
        basinID = self.eval_params.basinID
        # Determine calibration output directories
        output_dir = Path(agent.general.valid_path) if hasattr(agent, "general") else Path(agent.valid_path)
        # Use the Calibration_Run directory for single-run outputs
        output_dir = Path(agent.general.calib_path) if hasattr(agent, "general") else output_dir
        output_iter_path = output_dir / "Output_Iteration"
        plot_iter_path = output_dir / "Plot_Iteration"
        calib_path = output_dir / "Output_Calib"
        output_iter_path.mkdir(parents=True, exist_ok=True)
        plot_iter_path.mkdir(parents=True, exist_ok=True)
        calib_path.mkdir(parents=True, exist_ok=True)

        # Write simulation output files for iteration 0, best, and last (all identical in NoCalibModel)
        df = self.output  # DataFrame of simulation output (sim_flow vs time)
        df.to_csv(output_iter_path / f"{basinID}_output_iteration_{i:04d}.csv")
        df.to_csv(output_iter_path / f"{basinID}_output_best_iteration.csv")
        df.to_csv(output_iter_path / f"{basinID}_output_last_iteration.csv")

        # Log metrics and objective
        self.eval_params.write_metric_iter_file(i, obj_score, metrics)
        self.eval_params.write_objective_log_file(i, obj_score)

        # Write dummy parameter logs (NoCalibModel has no adjustable parameters)
        dummy_param_df = pd.DataFrame([{"model": "nocalib", "param": "none", str(i): 0.0}])
        self.eval_params.write_param_iter_file(i, dummy_param_df)
        self.eval_params.write_param_all_file(i, dummy_param_df)
        self.eval_params.write_last_iteration(i)
        # (No cost function history for NoCalibModel)

        # Optionally generate iteration plots if enabled (using existing plotting utilities)
        if getattr(self.eval_params, "save_plot_iter_flag", False):
            from ngen.cal.plot_output import plot_metric, plot_obj_fun, plot_streamflow, plot_scatterplot, plot_fdc
            try:
                plot_metric(agent)
                plot_obj_fun(agent)
            except Exception:
                pass  # Some plot functions may rely on calibration context
            # Generate standard iteration plots (hydrograph, scatter, FDC) for single run
            plot_streamflow(agent, df, self.observed, basinID, plot_iter_path, title="Streamflow")
            plot_scatterplot(agent, df, self.observed, basinID, plot_iter_path)
            plot_fdc(agent, df, self.observed, basinID, plot_iter_path)

        # After saving calibration outputs, generate validation config files
        self.create_validation_configs(agent)

    @property
    def adjustables(self):
        """Return empty list since NoCalibModel has no calibratable parameters."""
        return []

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

    def write_cost_iter_file(self, i, path):
        # No-op for single-run NoCalibModel
        pass

    def write_run_complete_file(self, run_name: str, workdir: Path):
        """Write a simple completion file for single-run NoCalibModel."""
        complete_file = workdir / f"{run_name}_complete.txt"
        with open(complete_file, "w") as f:
            f.write("Single-run execution complete.\n")



class NoCalibModel(ModelExec):
    type: Literal["nocalib"] = "nocalib"
    strategy: Optional[str] = Field(default="uniform")

    realization: Path
    catchments: Path
    nexus: Path
    obsflow: Path

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
        logger.info("[NoCalibModel] Post-processing validation run (Single Exec)")

        from ngen.cal.plot_output import plot_valid_output
        from ngen.cal.metric_functions import calc_metrics_df

        basin_id = self.basinID
        valid_path = agent.valid_path
        valid_plot_path = agent.valid_path_plot

        # Step 1: Locate output
        csv_files = list(Path(valid_path).glob(f"{basin_id}_output*.csv"))
        if not csv_files:
            raise FileNotFoundError(f"No simulation output file found for {basin_id} in {valid_path}")
        self._output_iter_file = str(csv_files[0])
    
        # Step 2: Compute metrics and save
        df_sim = pd.read_csv(self._output_iter_file, index_col=0, parse_dates=True)
        df_obs = pd.read_csv(self.obsflow, index_col=0, parse_dates=True)
        df = pd.DataFrame({"sim_flow": df_sim.iloc[:, 0], "obs_flow": df_obs.iloc[:, 0]})
        df = df.loc[self.eval_params.eval_start : self.eval_params.eval_end]

        df_metrics = calc_metrics_df(df, self.eval_params)
        df_metrics.insert(0, 'label', 'valid_control')
        df_metrics.insert(0, 'run', 'valid_control')

        out_metrics = Path(valid_path) / f"{basin_id}_metrics_valid_control.csv"
        df_metrics.to_csv(out_metrics, index=False)
        logger.info(f"[NoCalibModel] Metrics written: {out_metrics}")

        # Step 3: Copy output with correct name
        target_output = Path(valid_path) / f"{basin_id}_output_valid_control.csv"
        shutil.copy2(self._output_iter_file, target_output)

        # Step 4: Generate plots
        runs = ['valid_control']
        plot_valid_output(self, agent, runs, self.eval_params.time_period)
        logger.info("[NoCalibModel] Validation post-processing complete.")

    def postprocess_single_validation_output_last(self, output_dir: Path, basin_id: str):
            import shutil
            import pandas as pd
            from .search import _calc_metrics as calculate_all_metrics
            from .plot_output import hydrograph_valid, fdc_plot_valid, barplot_metrics_valid, streamflow_precip_valid

            logger.info(f"[NoCalibModel] Post-processing validation output for basin {basin_id}...")

            plot_dir = output_dir / "Plot_Valid"
            plot_dir.mkdir(parents=True, exist_ok=True)

            output_src = output_dir / "Output_Iteration" / f"{basin_id}_output_iteration_0000.csv"
            output_dst = output_dir / f"{basin_id}_output_valid_control.csv"
            shutil.copy(output_src, output_dst)

            df = self.align_obs_and_sim(output_dst, self.obsflow)
            self.metrics = calculate_all_metrics(df["sim_flow"], df["obs_flow"], self.eval_params.threshold)
            df_metrics = pd.DataFrame([self.metrics])
            metrics_dst = output_dir / f"{basin_id}_metrics_valid_control.csv"
            df_metrics.to_csv(metrics_dst, index=False)

            hydrograph_valid(df, plot_dir, basin_id, label="Valid_Run")
            fdc_plot_valid(df, plot_dir, basin_id, label="Valid_Run")
            barplot_metrics_valid(df_metrics, plot_dir, basin_id, label="Valid_Run")

            if self.precip_forcing and self.precip_forcing.exists():
                streamflow_precip_valid(df, self.precip_forcing, plot_dir, basin_id, label="Valid_Run")

            logger.info(f"[NoCalibModel] Validation post-processing completed.")

        
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
        

    def write_cost_iter_file(self, i, path):
        # No-op for single-run NoCalibModel
        pass

Model.update_forward_refs()
