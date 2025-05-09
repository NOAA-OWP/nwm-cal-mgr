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

    def postprocess_single_run_output(self, output_dir: Path, basin_id: str, output_iter_path: Path):
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

    def postprocess_single_run_output_p3(self, workdir, basin_id, output_iter_path):
        """
        Postprocess output for single-run execution and calculate evaluation metrics.
        """
        import shutil
        from datetime import datetime
        from .search import calculate_all_metrics

        output_dir = Path(workdir)
        output_iter_path.mkdir(parents=True, exist_ok=True)

        # Locate a nexus CSV output file
        matches = list(output_dir.glob(f"nex-{basin_id}*_output.csv"))
        if not matches:
            matches = list(output_dir.glob("nex-*_output.csv"))
            if not matches:
                raise FileNotFoundError(f"No output file matching nex-{basin_id}*.csv found in {output_dir}")
            nex_file = matches[0]
            warnings.warn(f"Using fallback output file: {nex_file.name}", RuntimeWarning)
        else:
            nex_file = matches[0]

        # Read and assign headers if missing
        df_raw = pd.read_csv(nex_file, header=None, names=["Time", "sim_flow"], parse_dates=["Time"])
        df_raw.set_index("Time", inplace=True)

        # Write the standardized output CSV
        output_file = output_iter_path / f"{basin_id}_output_iteration_0000.csv"
        df_raw.to_csv(output_file)
        self._output_iter_file = output_file
        logger.info(f"[NoCalibModel] Wrote: {output_file}")

        # Copy raw outputs to Output_Calib
        output_calib_path = output_dir / "Output_Calib"
        output_calib_path.mkdir(exist_ok=True)
        for f in output_dir.glob("*.csv"):
            shutil.copy(f, output_calib_path)
        logger.info(f"[NoCalibModel] Copied raw outputs to {output_calib_path}")

        # Load observed flow
        obs = self.get_obsflow()

        # Determine evaluation range (match validation_run.py logic)
        eval_range = self.evaluation_range
        if not isinstance(eval_range, (list, tuple)) or len(eval_range) != 2:
            eval_range = [df_raw.index[0], df_raw.index[-1]]
            logger.warning(f"[NoCalibModel] Invalid evaluation_range; defaulting to full range: {eval_range}")

        # Align time slices
        obs_sliced = obs.loc[eval_range[0]:eval_range[1]]
        sim_sliced = df_raw.loc[eval_range[0]:eval_range[1]]

        # Merge on datetime index
        df = pd.merge(obs_sliced, sim_sliced, left_index=True, right_index=True, how='inner')
        df.columns = ['obs_flow', 'sim_flow']

        # If no overlap, log and fill with NaNs
        if df.empty:
            logger.warning("Cannot compute objective function, do time indicies align?")
            self.metrics = {k.lower(): float('nan') for k in [
                'KGE', 'NSE', 'RMSE', 'MAE', 'CORR', 'RSR', 'PBIAS'
            ]}
        else:
            self.metrics = {
                k.lower(): v for k, v in calculate_all_metrics(
                    df["obs_flow"], df["sim_flow"], self.threshold
                ).items()
            }

        print(f'self.metrics : {self.metrics}')
        print(f'self.eval_params.objective : {self.eval_params.objective}')

        # Ensure objective metric exists
        obj_key = self.eval_params.objective.lower()
        if obj_key not in self.metrics:
            logger.error(
                f"[NoCalibModel] Objective function metric '{obj_key}' not found. "
                f"Available metrics: {list(self.metrics.keys())}"
            )
            raise ValueError(f"Objective function metric '{obj_key}' not found in metrics")

        logger.info("[NoCalibModel] Post-processing of single-run output completed.")

    #logger = logging.getLogger("NGEN_CAL")

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

    def postprocess_single_run_output_p(self, workdir, basin_id, output_iter_path):
        """
        Postprocesses output for a single-run non-calibratable model:
        - Copies all CSV outputs to Output_Calib
        - Writes a nex-{basin_id} style file with headers to Output_Iteration
        - Computes metrics and stores them
        """
        output_dir = Path(workdir)
        iter_dir = Path(output_iter_path)
        iter_dir.mkdir(parents=True, exist_ok=True)

        # --- Step 1: Locate nex-* file ---
        nex_file = next(output_dir.glob(f"nex-{basin_id}*_output.csv"), None)
        if not nex_file:
            fallback = list(output_dir.glob("nex-*_output.csv"))
            if not fallback:
                raise FileNotFoundError(f"No output file matching nex-{basin_id}*.csv found in {output_dir}")
            nex_file = fallback[0]
            warnings.warn(f"Using fallback output file: {nex_file.name}", RuntimeWarning)

        # --- Step 2: Read and format output ---
        df_raw = pd.read_csv(nex_file, header=None, names=["Time", "sim_flow"], parse_dates=["Time"])
        df_raw.set_index("Time", inplace=True)

        # --- Step 3: Write output_iteration CSV ---
        output_file = iter_dir / f"{basin_id}_output_iteration_0000.csv"
        df_raw.to_csv(output_file)
        logger.info(f"[NoCalibModel] Wrote: {output_file}")

        # --- Step 4: Copy CSV outputs to Output_Calib ---
        calib_dir = output_dir / "Output_Calib"
        calib_dir.mkdir(exist_ok=True)
        for f in output_dir.glob("*.csv"):
            shutil.copy2(f, calib_dir)
        logger.info(f"[NoCalibModel] Copied raw outputs to {calib_dir}")

        # --- Step 5: Load observed flow ---
        obs = self.get_obsflow()

        # --- Step 6: Determine valid evaluation range ---
        eval_range = self.evaluation_range
        if not isinstance(eval_range, (list, tuple)) or len(eval_range) != 2:
            eval_range = [df_raw.index[0], df_raw.index[-1]]
            logger.warning(f"[NoCalibModel] Invalid evaluation_range; defaulting to full time range: {eval_range}")

        # --- Step 7: Slice and compute metrics ---
        df_sliced = df_raw.loc[eval_range[0]:eval_range[1]]
        simflow = df_sliced["sim_flow"]

        metrics_upper = calculate_all_metrics(obs, simflow, eval_range, self.threshold)
        self.metrics = {k.lower(): v for k, v in metrics_upper.items()}
        print(f'self.metrics : {self.metrics}')
        print(f'self.eval_params.objective : {self.eval_params.objective}')

        if self.eval_params.objective not in self.metrics:
            logger.error(
                f"[NoCalibModel] Objective function metric '{self.eval_params.objective}' not found. "
                f"Available metrics: {list(self.metrics.keys())}"
            )
            raise ValueError(f"Objective function metric '{self.eval_params.objective}' not found in metrics")

        self._output_iter_file = output_file
        logger.info("[NoCalibModel] Post-processing of single-run output completed.")


    def postprocess_single_run_output_past2(self, workdir: Path, basin_id: str, output_iter_path: Path):
        output_dir = Path(workdir)
        output_iter_path.mkdir(parents=True, exist_ok=True)

        # Find NGen nexus output file
        matches = list(output_dir.glob(f"nex-{basin_id}*_output.csv"))
        if not matches:
            fallback = list(output_dir.glob("nex-*_output.csv"))
            if fallback:
                nex_file = fallback[0]
                warnings.warn(f"Using fallback output file: {nex_file.name}", RuntimeWarning)
            else:
                raise FileNotFoundError(f"No output file matching nex-{basin_id}*.csv found in {output_dir}")
        else:
            nex_file = matches[0]

        # Load NGen output assuming no header, and assign column names
        df_raw = pd.read_csv(nex_file, header=None, names=["Time", "sim_flow"], parse_dates=["Time"])
        df_raw.set_index("Time", inplace=True)

        # Save formatted CSV for plotting and evaluation
        output_file = output_iter_path / f"{basin_id}_output_iteration_0000.csv"
        df_raw.to_csv(output_file)
        self._output_iter_file = output_file
        logger.info(f"[NoCalibModel] Wrote: {output_file}")

        # Copy all outputs to Output_Calib directory
        out_calib = output_dir / "Output_Calib"
        out_calib.mkdir(exist_ok=True)
        for f in output_dir.glob("cat-*.csv"):
            shutil.copy2(f, out_calib)
        for f in output_dir.glob("nex-*.csv"):
            shutil.copy2(f, out_calib)
        logger.info(f"[NoCalibModel] Copied raw outputs to {out_calib}")

        # Load observed flow
        obs = self.get_obsflow()

        # Evaluate metrics
        self.metrics = _calc_metrics(
            simulated_hydrograph=df_raw["sim_flow"],
            observed_hydrograph=obs,
            eval_range=self.evaluation_range,
            threshold=self.threshold,
        )

        if not self.metrics or self.eval_params.objective not in self.metrics:
            logger.error(
                f"[NoCalibModel] Objective function metric '{self.eval_params.objective}' not found. "
                f"Available metrics: {list(self.metrics.keys()) if self.metrics else 'None'}"
            )
            raise ValueError(
                f"Objective function metric '{self.eval_params.objective}' not found in metrics"
            )

    def postprocess_single_run_output_past(self, workdir: Path, basin_id: str, output_iter_path: Path):
        import shutil
        import pandas as pd
        from datetime import datetime

        # Ensure output dirs exist
        output_iter_path.mkdir(parents=True, exist_ok=True)
        output_calib_path = workdir / "Output_Calib"
        output_calib_path.mkdir(parents=True, exist_ok=True)

        # Look for nex-* file
        output_dir = Path(workdir)
        matches = list(output_dir.glob(f"nex-{basin_id}*_output.csv"))
        if not matches:
            fallback = list(output_dir.glob("nex-*_output.csv"))
            if not fallback:
                raise FileNotFoundError(f"No output file matching nex-{basin_id}*.csv found in {output_dir}")
            nex_file = fallback[0]
            warnings.warn(f"Using fallback output file: {nex_file.name}", RuntimeWarning)
        else:
            nex_file = matches[0]

        # Read nex-* file with no header, apply correct columns
        df_raw = pd.read_csv(nex_file, header=None, names=["Time", "sim_flow"], parse_dates=["Time"])
        df_raw.set_index("Time", inplace=True)

        # Save standardized iteration output
        output_file = output_iter_path / f"{basin_id}_output_iteration_0000.csv"
        df_raw.to_csv(output_file)
        self._output_iter_file = output_file

        logger.info(f"[NoCalibModel] Wrote: {output_file}")

        # Copy all outputs to Output_Calib
        for f in output_dir.glob("*.csv"):
            shutil.copy(f, output_calib_path)

        logger.info(f"[NoCalibModel] Copied raw outputs to {output_calib_path}")

        # Load observed data
        obs = self.get_obsflow()

        # Compute metrics using shared evaluation method
        self.metrics = _calc_metrics(
            simulated_hydrograph=df_raw["sim_flow"],
            observed_hydrograph=obs,
            eval_range=self.evaluation_range,
            threshold=self.threshold,
        )


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

    def write_iteration_outputs(self, agent, metrics: dict, score: float):
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

    def write_iteration_outputs_last(self, agent, metrics: dict, obj_score: float):
        i = 0
        basinID = self.eval_params.basinID
        if not basinID:
            raise ValueError("basinID must be defined for EvaluationOptions in single-run mode.")

        # Write iteration outputs
        df = self.output
        df.to_csv(str(Path(agent.output_iter_path) / f"{basinID}_output_iteration_{i:04d}.csv"))
        df.to_csv(str(Path(agent.output_iter_path) / f"{basinID}_output_best_iteration.csv"))
        df.to_csv(str(Path(agent.output_iter_path) / f"{basinID}_output_last_iteration.csv"))

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
        self.eval_params.write_cost_iter_file(i, agent.calib_path)
        self.eval_params.write_run_complete_file("calib", agent.calib_path)

    '''
    def get_args(self) -> str:
        return f"{self.catchments} all {self.nexus} all {self.realization}"

    def update_config(self, i: int, params: pd.DataFrame, id=None, path=Path(".")):
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
    def output_old(self) -> pd.DataFrame:
        """Dynamically locate the simulation output CSV."""
        basin_id = self.eval_params.basinID
        pattern = f"{basin_id}_output_iteration_*.csv"

        search_path = Path(self.realization).parent
        matches = list(search_path.rglob(pattern))

        if matches:
            try:
                return pd.read_csv(matches[0], index_col=0, parse_dates=True)
            except Exception as e:
                raise RuntimeError(f"Failed to load output file {matches[0]}: {e}")
        else:
            raise FileNotFoundError(f"No simulation output file found for pattern: {pattern}")


    def postprocess_single_run_output3(self, output_dir: Path, basin_id: str, output_iter_path: Path) -> None:
        """
        Postprocess the output of a single-run model:
        - Copy cat-* and nex-* files into Output_Calib
        - Create <basinID>_output_iteration_0000.csv in Output_Iteration using a selected nex-* file
        """
        import shutil
        import pandas as pd
        import logging

        logger = logging.getLogger(__name__)

        output_dir = Path(output_dir)
        iter_dir = Path(output_iter_path)
        output_calib_dir = output_dir / "Output_Calib"
        output_calib_dir.mkdir(exist_ok=True)
        iter_dir.mkdir(exist_ok=True)

        # Step 1: Select a nex-* file (best guess: the first one) to represent the output for the basin
        nex_files = sorted(output_dir.glob("nex-*_output.csv"))
        if not nex_files:
            raise FileNotFoundError(f"No nex-* output file found in {output_dir}")

        selected_nex_file = nex_files[0]
        df = pd.read_csv(selected_nex_file)

        # Step 2: Save it as <basinID>_output_iteration_0000.csv in Output_Iteration
        output_iter_file = iter_dir / f"{basin_id}_output_iteration_0000.csv"
        df.to_csv(output_iter_file, index=False)


        # Step 3: Move cat-* and nex-* outputs into Output_Calib
        for pattern in ["cat-*.csv", "nex-*_output.csv"]:
            for file in output_dir.glob(pattern):
                shutil.move(file, output_calib_dir)

        logger.info(f"[NoCalibModel] Wrote: {output_iter_file}")
        logger.info(f"[NoCalibModel] Copied raw outputs to {output_calib_dir}")

    def postprocess_single_run_output2(self, output_dir: Path, basin_id: str, output_iter_path: Path) -> None:
        """
        Postprocess the output of a single-run model:
        - Copy cat-* and nex-* files into Output_Calib
        - Create <basinID>_output_iteration_0000.csv in Output_Iteration using nex-<basinID>_output.csv if available
        - Merge with precipitation if available
        """
        import shutil
        import pandas as pd
        import logging

        logger = logging.getLogger(__name__)
        output_dir = Path(output_dir)
        iter_dir = Path(output_iter_path)
        output_calib_dir = output_dir / "Output_Calib"
        output_calib_dir.mkdir(exist_ok=True)
        iter_dir.mkdir(exist_ok=True)

        # Step 1: Copy cat-* and nex-* outputs into Output_Calib
        for pattern in ["cat-*.csv", "nex-*_output.csv"]:
            for file in output_dir.glob(pattern):
                shutil.copy(file, output_calib_dir)

        # Step 2: Select correct nex file
        nex_file = output_dir / f"nex-{basin_id}_output.csv"
        if not nex_file.exists():
            nex_files = sorted(output_dir.glob("nex-*_output.csv"))
            if not nex_files:
                raise FileNotFoundError(f"No nex-* output file found in {output_dir}")
            nex_file = nex_files[0]
            logger.warning(f"Using fallback output file: {nex_file.name}")

        df = pd.read_csv(nex_file)

        # Step 3: Merge precipitation if available
        if hasattr(self, "df_precip") and self.df_precip is not None:
            try:
                df_precip = self.df_precip.copy()
                df_precip["Time"] = pd.to_datetime(df_precip["Time"])
                df["Time"] = pd.to_datetime(df["Time"])
                df = pd.merge(df, df_precip, on="Time", how="left")
                logger.info("Merged precipitation into output streamflow.")
            except Exception as e:
                logger.warning(f"Failed to merge precipitation: {e}")

        # Step 4: Save output_iteration_0000 file
        output_iter_file = iter_dir / f"{basin_id}_output_iteration_0000.csv"
        df.to_csv(output_iter_file, index=False)

        logger.info(f"[NoCalibModel] Wrote: {output_iter_file}")
        logger.info(f"[NoCalibModel] Copied raw outputs to {output_calib_dir}")

    @property
    def output3(self) -> pd.DataFrame:
        """Load the main model output file for plotting/evaluation."""
        if not self._output_iter_file or not self._output_iter_file.exists():
            raise FileNotFoundError(f"No simulation output file found at: {self._output_iter_file}")
        return pd.read_csv(self._output_iter_file, index_col=0, parse_dates=True)

    @property
    def output2(self) -> pd.DataFrame:
        base = str(self.eval_params.output_iter_file)
        matches = glob.glob(base + "*.csv")
        if not matches:
            raise FileNotFoundError(f"No simulation output file found for pattern: {base}*.csv")
        return pd.read_csv(matches[0], index_col=0, parse_dates=True)

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
        """Alias for realization file (for compatibility with validation logic)"""
        return self.realization
    '''
Model.update_forward_refs()
