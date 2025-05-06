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

from pydantic import BaseModel, Field, DirectoryPath

from .model import PosInt
from .model import ModelExec
from .ngen import Ngen
from .strategy import Estimation, Sensitivity
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


import shutil

class NoCalibModel(ModelExec):
    type: Literal["nocalib"] = "nocalib"
    strategy: Optional[str] = Field(default="uniform")

    realization: Path
    catchments: Path
    nexus: Path
    obsflow: Path

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

    def postprocess_single_run_output(self, workdir: Path, basin_id: str):
        """
        Locate the ngen simulation output and copy/rename it to expected path
        for evaluation in calibration workflow.
        """
        # This is typically the filename pattern used in valid runs
        output_dir = Path(workdir)
        matches = list(output_dir.glob(f"**/{basin_id}*.csv"))

        if not matches:
            raise FileNotFoundError(f"No ngen output CSV found for basin ID: {basin_id} in {output_dir}")

        dest = self.eval_params.output_iter_file.with_suffix(".csv")
        shutil.copy(matches[0], dest)

    @property
    def output(self) -> pd.DataFrame:
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
class NoCalibModel(ModelExec):
    type: Literal["nocalib"] = "nocalib"
    strategy: Optional[str] = "uniform"

    realization: Path
    catchments: Path
    nexus: Path
    obsflow: Path  # Observed flow file required

    def resolve_paths(self):
        self.realization = self.realization.resolve()
        self.catchments = self.catchments.resolve()
        self.nexus = self.nexus.resolve()
        self.obsflow = self.obsflow.resolve()

    def get_args(self) -> str:
        return f'{self.catchments} "all" {self.nexus} "all" {self.realization}'

    def update_config(self, i: int, params: pd.DataFrame, id=None, path=Path(".")):
        # For single-run models, we assume config is fixed — nothing to update
        pass

    @property
    def adjustables(self):
        # No adjustable parameters in single-run
        return []

    @property
    def output(self) -> pd.DataFrame:
        # Return first matching output CSV file written by ngen
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

    def write_iteration_outputs(self, agent, metrics: dict, obj_score: float):
        """
        Manually write standard calibration outputs for this non-calibratable model.

        Called from inside `_evaluate()` in search.py.
        """
        i = 0
        basinID = self.eval_params.basinID
        if not basinID:
            raise ValueError("basinID must be defined for EvaluationOptions in single-run mode.")

        # Write output CSV as best/last
        iter_file = self.eval_params.output_iter_file
        df = self.output
        df.to_csv(str(agent.output_iter_path / f"{basinID}_output_iteration_{i}.csv"))

        # Copy to best/last iteration aliases
        df.to_csv(str(agent.output_iter_path / f"{basinID}_output_best_iteration.csv"))
        df.to_csv(str(agent.output_iter_path / f"{basinID}_output_last_iteration.csv"))

        # Metrics and params
        self.eval_params.write_metric_iter_file(i, obj_score, metrics)
        self.eval_params.write_objective_log_file(i, obj_score)

        # Fake params
        dummy_param_df = pd.DataFrame([{
            "model": "nocalib",
            "param": "none",
            str(i): 0.0
        }])
        self.eval_params.write_param_iter_file(i, dummy_param_df)
        self.eval_params.write_param_all_file(i, dummy_param_df)
        self.eval_params.write_last_iteration(i)
        self.eval_params.write_cost_iter_file(i, agent.calib_path)

        # Write run-complete marker
        self.eval_params.write_run_complete_file("calib", agent.calib_path)

        # Optional plotting (if enabled)
        if self.eval_params.save_plot_iter_flag:
            from ngen.cal.plot_output import plot_metric, plot_obj_fun, plot_streamflow, plot_scatterplot, plot_fdc
            plot_metric(agent)
            plot_obj_fun(agent)
            plot_streamflow(agent, df, self.observed, basinID, agent.plot_iter_path, title="Streamflow")
            plot_scatterplot(agent, df, self.observed, basinID, agent.plot_iter_path)
            plot_fdc(agent, df, self.observed, basinID, agent.plot_iter_path)

    @property
    def realization_file(self) -> Path:
        """Alias for realization file (for compatibility with validation logic)"""
        return self.realization
'''

Model.update_forward_refs()
