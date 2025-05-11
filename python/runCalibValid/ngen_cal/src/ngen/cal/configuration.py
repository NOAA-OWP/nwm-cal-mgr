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

    def postprocess_single_run_output(self, workdir: Path, basin_id: str, output_iter_path: Path):
        import shutil
        import pandas as pd
        import logging
        from ngen.cal import metric_functions as mf
        from ngen.cal import plot_functions as pf

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
        '''

        # Read files
        #sim_file = next((output_iter_path / f).resolve() for f in output_iter_path.glob(f"nex-{catchment_id}*_output.csv"))
        sim_file = self._output_iter_file
        sim_df = pd.read_csv(sim_file, index_col=0, parse_dates=True).rename(columns={sim_file.stem.split("_")[0]: "sim_flow"})
        obs_df = pd.read_csv(self.obsflow, index_col=0, parse_dates=True).rename(columns={obs_df.columns[0]: "obs_flow"})

        # Merge and align
        df = pd.merge(obs_df, sim_df, left_index=True, right_index=True, how='inner')
        '''
        logger.info(f"eval_range : {self.evaluation_range}")
        logger.info(f"{df.head()}")

        # Compute metrics
        '''
        self.metrics = mf.evaluate_metrics(
            df["sim_flow"], df["obs_flow"],
            metrics=self.eval_params.metrics,
            range=self.eval_params.evaluation_range
        )
        '''
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
        pf.plot_streamflow(df_hydro, plot_iter_path / f"{basin_id}_hydrograph_single_run.png", title)

        # Flow Duration Curve
        df_fdc = df.rename(columns={"obs_flow": "Observation", "sim_flow": "SingleRun"})
        pf.plot_fdc_calib(df_fdc, plot_iter_path / f"{basin_id}_fdc_single_run.png", title)

        # Scatterplot
        df_scat = df.rename(columns={"obs_flow": "Observation", "sim_flow": "SingleRun"})
        df_scat["Time"] = df.index
        pf.scatterplot_streamflow(df_scat, plot_iter_path / f"{basin_id}_scatter_single_run.png", title)

        logger.info(f"[NoCalibModel] Post-processing of single-run output completed.")

    def postprocess_single_run_output_path_last(self, workdir: Path, basin_id: str, output_dir: Optional[Path] = None):
        """
        Locate the ngen simulation output and copy/rename it to expected path
        for evaluation in calibration workflow.
        Also performs plotting and stores all iteration results to Output_Iteration.
        """
        from .plot_functions import plot_streamflow, plot_fdc_calib
        # from .plot_output import plot_objfunc

        output_dir = Path(output_dir or workdir)
        output_iter_path = output_dir / "Output_Iteration"
        output_iter_path.mkdir(parents=True, exist_ok=True)

        plot_iter_path = output_dir / "Plot_Iteration"
        plot_iter_path.mkdir(parents=True, exist_ok=True)

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
        #self.eval_params.write_plots(output_iter_path, df["sim_flow"], df["obs_flow"])

        # Save comparison data
        try:
            comparison_file = output_iter_path / f"{basin_id}_comparison.csv"
            df.to_csv(comparison_file)
            logger.info(f"[NoCalibModel] Saved comparison CSV: {comparison_file}")

            # Generate plots
            plot_streamflow(df, plot_iter_path, basin_id)
            #plot_scatter(df, plot_iter_path, basin_id)
            plot_fdc_calib(df, plot_iter_path, basin_id)
            #plot_objfunc([df], plot_iter_path, basin_id)
            logger.info("[NoCalibModel] Plots generated successfully.")
        except Exception as e:
            raise (e)

        logger.info("[NoCalibModel] Post-processing of single-run output completed.")


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
