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


class NoCalibModel(ModelExec):
    type: Literal["nocalib"] = "nocalib"
    strategy: Optional[str] = Field(default="uniform")

    realization: Path
    catchments: Path
    nexus: Path
    obsflow: Path

    objective_score: Optional[float] = None 
    _output_iter_file: Path = PrivateAttr(default=None)
    #metrics: Optional[dict] = None  # Ensure metrics can be assigned
    evaluation_range: Optional[List[datetime]] = None

    metrics: Optional[Dict[str, float]] = None

    def postprocess_single_run_output(self, workdir: Path, basin_id: str, output_dir: Optional[Path] = None):
        """
        Locate the ngen simulation output and copy/rename it to expected path
        for evaluation in calibration workflow.
        Also performs plotting and stores all iteration results to Output_Iteration.
        """
        output_dir = Path(output_dir or workdir)
        output_iter_path = output_dir / "Output_Iteration"
        output_iter_path.mkdir(parents=True, exist_ok=True)

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

        # Step 4: Copy cat-* and nex-*output.csv to Output_Calib
        output_calib_path = workdir / "Output_Calib"
        output_calib_path.mkdir(parents=True, exist_ok=True)

        for file in workdir.glob("cat-*.csv"):
            shutil.move(file, output_calib_path)
        for file in workdir.glob("nex-*_output.csv"):
            shutil.move(file, output_calib_path)

        logger.info(f"[NoCalibModel] Copied raw outputs to {output_calib_path}")

        # Step 5: Compute and store metrics
        obs = self.get_obsflow()
        df = pd.concat([df_raw["sim_flow"], obs], axis=1).dropna()
        df.columns = ["sim_flow", "obs_flow"]
        df = df.loc[self.evaluation_range[0]:self.evaluation_range[1]]

        #self.output = df

        self.metrics = calculate_all_metrics(
            df["obs_flow"], df["sim_flow"], self.evaluation_range, self.threshold
        )

        logger.info(f"eval_range : {self.evaluation_range}")
        logger.info(f"self.metrics : {self.metrics}")
        logger.info(f"self.eval_params.objective : {self.eval_params.objective}")


        score = self.metrics.get(self.eval_params.objective, None)
        if score is None:
            score = self.metrics.get(self.eval_params.objective.upper(), None)
            if score is None:
                raise ValueError(f"Objective function metric '{self.eval_params.objective}' not found in metrics")
        self.write_iteration_outputs(output_dir, self.metrics, score)

        # Step 6: Save metrics and plots using regular workflow method
        #self.eval_params.write_metric_iter_file(self.metrics, output_iter_path)
        self.eval_params.write_plots(output_iter_path, df["sim_flow"], df["obs_flow"])

        # Save comparison data
        try:
            comparison_file = output_iter_dir / f"{basin_id}_comparison.csv"
            df.to_csv(comparison_file)
            logger.info(f"[NoCalibModel] Saved comparison CSV: {comparison_file}")

            # Generate plots
            plot_streamflow(df, plot_iter_dir, basin_id)
            plot_scatter(df, plot_iter_dir, basin_id)
            plot_fdc(df, plot_iter_dir, basin_id)
            plot_objfunc([df], plot_iter_dir, basin_id)
            logger.info("[NoCalibModel] Plots generated successfully.")
        except Exception as e:
            raise (e)

        logger.info("[NoCalibModel] Post-processing of single-run output completed.")


    def postprocess_single_run_output_new(self, workdir: Path, basin_id: str, output_iter_dir: Path, plot_iter_dir: Path):
        """
        Post-process single-run outputs:
        - Copy all 'cat-*.csv' and 'nex-*_output.csv' to Output_Iteration.
        - Generate plots using existing validation-style logic.
        - Save comparison data and metrics.
        """
        try:
            logger.info("[NoCalibModel] Post-processing single-run output...")

            output_dir = Path(workdir)
            catchment_csvs = list(output_dir.glob("cat-*.csv"))
            nex_output_csvs = list(output_dir.glob("nex-*_output.csv"))

            if not catchment_csvs and not nex_output_csvs:
                raise FileNotFoundError(f"No ngen output files found in {output_dir}")

            # Copy files to Output_Iteration
            for f in catchment_csvs + nex_output_csvs:
                shutil.copy(f, output_iter_dir)
                logger.info(f"[NoCalibModel] Copied: {f.name} -> {output_iter_dir}")

            # Prepare DataFrame for plotting and metrics
            df_sim = self.output  # Assumes sim data is set as DataFrame with datetime index and 'sim_flow'
            df_obs = self.observed  # Assumes obs data is set as DataFrame with datetime index and 'obs_flow'

            df = pd.merge(df_sim, df_obs, left_index=True, right_index=True)
            df.columns = ['sim_flow', 'obs_flow']

            logger.info(f"[NoCalibModel] Final merged DataFrame shape: {df.shape}")

            # Save comparison data
            comparison_file = output_iter_dir / f"{basin_id}_comparison.csv"
            df.to_csv(comparison_file)
            logger.info(f"[NoCalibModel] Saved comparison CSV: {comparison_file}")

            # Generate plots
            plot_streamflow(df, plot_iter_dir, basin_id)
            plot_scatter(df, plot_iter_dir, basin_id)
            plot_fdc(df, plot_iter_dir, basin_id)
            plot_objfunc([df], plot_iter_dir, basin_id)
            logger.info("[NoCalibModel] Plots generated successfully.")

        except Exception as e:
            logger.error(f"Failed to postprocess single-run output: {e}")
            raise

    def postprocess_single_run_output_last(self, workdir: Path, basin_id: str, output_dir: Optional[Path] = None):
        """
        Locate the ngen simulation output and copy/rename it to expected path
        for evaluation in calibration workflow.
        Also performs plotting and stores all iteration results to Output_Iteration.
        """
        print(f'output_dir : {output_dir}')
        output_dir = Path(output_dir or workdir)
        output_calib_path = output_dir / "Output_Calib"
        output_iter_path = output_dir / "Output_Iteration"
        output_calib_path.mkdir(parents=True, exist_ok=True)
        output_iter_path.mkdir(parents=True, exist_ok=True)
        print(f'output_calib_path  : {output_calib_path}')

        # Copy cat-*.csv and nex-*_output.csv to Output_Calib
        cat_files = list(output_dir.glob("cat-*.csv"))
        nex_files = list(output_dir.glob("nex-*_output.csv"))

        if not cat_files and not nex_files:
            raise FileNotFoundError(f"No ngen output CSV found for basin ID: {basin_id} in {output_dir}")

        for f in cat_files + nex_files:
            shutil.copy(f, output_calib_path)

        # Use one nex output file for time series extraction
        nex_file = nex_files[0]
        df_raw = pd.read_csv(nex_file, header=None, names=["Time", "sim_flow"], parse_dates=["Time"])
        df_raw.set_index("Time", inplace=True)

        # Write to Output_Iteration only
        output_file = output_iter_path / f"{basin_id}_output_iteration_0000.csv"
        df_raw.to_csv(output_file)
        logger.info(f"[NoCalibModel] Wrote: {output_file}")

        obs = self.get_obsflow()
        df = pd.concat([df_raw["sim_flow"], obs], axis=1)
        df = df.loc[self.evaluation_range[0]:self.evaluation_range[1]]
        logger.info(f"Final merged DataFrame shape: {df.shape}")
        print(f'df A : \n{df}')

        # Evaluate metrics
        #df_raw = self.output
        #obs = self.observed
        #df = pd.concat([df_raw["sim_flow"], obs], axis=1).dropna()
        self._output = df

        logger.info("eval_range : {}".format(self.eval_params._eval_range))
        logger.info("Final merged DataFrame shape: {}".format(df.shape))

        metrics = calculate_all_metrics(df, self.observed, self.eval_params._eval_range, self.eval_params.threshold)
        self.metrics = metrics
        logger.info("metrics : {}".format(metrics))
        logger.info("agent.model.eval_params.objective : {}".format(self.eval_params.objective))

        score = metrics.get(self.eval_params.objective, None)
        if score is None:
            raise ValueError(f"Objective function metric '{self.eval_params.objective}' not found in metrics")
        self.write_iteration_outputs(output_dir, metrics, score)


    def postprocess_single_run_output_bak(self, output_dir: Path, basin_id: str, output_iter_path: Path):
        import pandas as pd
        import shutil
        import warnings
        from .search import _calc_metrics as calculate_all_metrics
        from .plot_output import generate_plots

        logger = logging.getLogger("NGEN_CAL")
        print(f'basin id : {basin_id}')
        
        # Attempt to find the output file
        matches = list(output_dir.glob(f"nex-{basin_id}*_output.csv"))
        if not matches:
            matches = list(output_dir.glob("nex-*_output.csv"))
            if not matches:
                raise FileNotFoundError(f"No output file matching nex-{basin_id}*.csv found in {output_dir}")
            warnings.warn(f"Using fallback output file: {matches[0].name}", RuntimeWarning)
        nex_file = matches[0]

        # Load simulated flow
        df_raw = pd.read_csv(nex_file, header=None, names=["Time", "sim_flow"], parse_dates=["Time"])
        df_raw.set_index("Time", inplace=True)

        # Load observed flow
        logger.info(f"self.obsflow : {self.obsflow}")
        obs = pd.read_csv(self.obsflow, index_col=0, parse_dates=True)
        obs.columns = ["obs_flow"]

        logger.info(f"obs : {obs.head()}")
        logger.info(f"df_raw:\n{df_raw.head()}")

        # Merge on common timestamps
        df = pd.concat([df_raw["sim_flow"], obs["obs_flow"]], axis=1).dropna()
        logger.info(f"df:\n{df.head()}")
        logger.info(f'df["obs_flow"]:\n{df["obs_flow"]}')
        logger.info(f'df["sim_flow"]:\n{df["sim_flow"]}')

        # Print evaluation range and merged shape
        logger.warning("Cannot compute objective function, do time indicies align?")
        logger.info(f"eval_range : ({df.index[0]}, {df.index[-1]})")
        logger.info(f"Final merged DataFrame shape: {df.shape}")

        # Evaluate metrics
        self.metrics = calculate_all_metrics(df)
        logger.info(f"self.metrics : {self.metrics}")
        logger.info(f"self.eval_params.objective : {self.eval_params.objective}")

        # Save evaluation-compatible file
        output_iter_path.mkdir(parents=True, exist_ok=True)
        output_file = output_iter_path / f"{basin_id}_output_iteration_0000.csv"
        df.to_csv(output_file)
        logger.info(f"[NoCalibModel] Wrote: {output_file}")

        # Store output file and range
        self.eval_params.output_iter_file = output_file
        self.eval_params._eval_range = [df.index[0], df.index[-1]]

        # Copy cat-* and nex-* files to Output_Calib (for plotting)
        output_calib = output_dir.parent / "Output_Calib"
        output_calib.mkdir(parents=True, exist_ok=True)
        for fpattern in [f"cat-{basin_id}*.csv", f"nex-{basin_id}*_output.csv"]:
            for file in output_dir.glob(fpattern):
                shutil.copy(file, output_calib / file.name)
                logger.info(f"[NoCalibModel] Copied {file.name} to Output_Calib")

        # Generate plots using existing logic
        generate_plots(
            self.eval_params,
            df=df,
            outdir=output_calib,
            log=logger
        )

    def postprocess_single_run_output2(self, output_dir: Path, basin_id: str, output_iter_path: Path):
        import pandas as pd
        import shutil
        import warnings
        import logging
        from .metric_functions import calculate_all_metrics

        logger = logging.getLogger("NGEN_CAL")

        # Look for the nexus output
        matches = list(output_dir.glob(f"nex-{basin_id}*_output.csv"))
        if not matches:
            # Try a fallback to any nex file
            matches = list(output_dir.glob("nex-*_output.csv"))
            if not matches:
                raise FileNotFoundError(f"No output file matching nex-{basin_id}*.csv found in {output_dir}")
            warnings.warn(f"Using fallback output file: {matches[0].name}", RuntimeWarning)

        nex_file = matches[0]
        # Assign headers because these files have none
        df_raw = pd.read_csv(nex_file, header=None, names=["Time", "sim_flow"], parse_dates=["Time"])
        df_raw.set_index("Time", inplace=True)

        output_iter_path.mkdir(parents=True, exist_ok=True)
        output_file = output_iter_path / f"{basin_id}_output_iteration_0000.csv"
        df_raw.to_csv(output_file)
        logger.info(f"[NoCalibModel] Wrote: {output_file}")

        self._output_iter_file = output_file

        # Also copy to Output_Calib for plotting
        calib_output_dir = output_dir / "Output_Calib"
        calib_output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(output_file, calib_output_dir / output_file.name)
        logger.info(f"[NoCalibModel] Copied raw outputs to {calib_output_dir}")

        # Load observed
        obs = self.get_obsflow()
        print(f'obs : {obs}')

        # Align by evaluation_range
        eval_range = self.evaluation_range
        if eval_range is not None:
            obs = obs.loc[eval_range[0]:eval_range[1]]
            df_raw = df_raw.loc[eval_range[0]:eval_range[1]]

        df = pd.concat([df_raw["sim_flow"], obs], axis=1)
        df.columns = ["sim_flow", "obs_flow"]
        df.dropna(inplace=True)

        print(f'df_raw:\n{df_raw}')
        print(f'df:\n{df}')
        print(f'df["obs_flow"]:\n{df["obs_flow"]}')
        print(f'df["sim_flow"]:\n{df["sim_flow"]}')

        logger.warning("Cannot compute objective function, do time indicies align?")
        logger.info(f"eval_range : {eval_range}")
        logger.info(f"Final merged DataFrame shape: {df.shape}")

        # Compute metrics
        if not df.empty:
            self.metrics = calculate_all_metrics(
                df["obs_flow"], df["sim_flow"], self.threshold
            )
        else:
            self.metrics = {}

        logger.info(f"self.metrics : {self.metrics}")
        logger.info(f"self.eval_params.objective : {self.eval_params.objective}")

        # Match objective function case
        obj_key = self.eval_params.objective.upper()
        if obj_key not in self.metrics:
            logger.error(f"[NoCalibModel] Objective function metric '{obj_key}' not found. Available metrics: {list(self.metrics.keys())}")
            raise ValueError(f"Objective function metric '{obj_key}' not found in metrics")

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
        self.eval_params.write_cost_iter_file(i, calib_path)
        self.eval_params.write_run_complete_file("calib", calib_path)

        # Plotting
        if self.eval_params.save_plot_iter_flag:
            from ngen.cal.plot_output import plot_metric, plot_obj_fun, plot_streamflow, plot_scatterplot, plot_fdc
            plot_metric(agent)
            plot_obj_fun(agent)
            plot_streamflow(agent, df, self.observed, basinID, plot_iter_path, title="Streamflow")
            plot_scatterplot(agent, df, self.observed, basinID, plot_iter_path)
            plot_fdc(agent, df, self.observed, basinID, plot_iter_path)
        

    def write_iteration_outputs_bak(self, agent, metrics: dict, score: float):
        import pandas as pd
        from pathlib import Path
        import logging

        logger = logging.getLogger(__name__)
        i = 0  # Always iteration 0 for single-run

        # Write metrics to Output_Iteration
        df = pd.DataFrame.from_dict(metrics, orient="index", columns=["value"])
        basinID = self.eval_params.basinID
        output_path = Path(agent.output_iter_path)
        output_file = output_path / f"{basinID}_output_iteration_{i:04d}.csv"
        df.to_csv(output_file)
        logger.info(f"[NoCalibModel] Wrote: {output_file}")

        # Write to Output_Calib as well
        calib_path = Path(agent.calib_path)
        df.to_csv(calib_path / f"{basinID}_output_calib_{i:04d}.csv")
        logger.info(f"[NoCalibModel] Copied raw outputs to {calib_path}")

        # Save cost function log for compatibility
        df_log = pd.DataFrame([{
            "best_objective_function": score,
            "final_objective_function": score
        }])
        df_log.to_csv(calib_path / "cost_function_log.csv", index=False)

    def write_cost_iter_file(self, i, path):
        # No-op for single-run NoCalibModel
        pass

Model.update_forward_refs()
