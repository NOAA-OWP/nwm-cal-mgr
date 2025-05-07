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


    def postprocess_single_run_output(self, output_dir: Path, basin_id: str, output_iter_path: Path) -> None:
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

Model.update_forward_refs()
