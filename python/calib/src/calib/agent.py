"""
This module creates working directory and subdirectories, and stores
properties related to configurations for executing calibration and validation runs.

@author: Nels Frazer, Xia Feng
"""

import os

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from calib.meta import JobMeta

from .configuration import Model
from .utils import pushd

import ewts
from common import get_calmgr_logger
logger = get_calmgr_logger()

if TYPE_CHECKING:
    from typing import Any, Mapping, Sequence

    from pandas import DataFrame

    from calib.calibratable import Adjustable


class BaseAgent(ABC):
    """Abstract interface for Agent class."""

    @property
    def adjustables(self) -> "Sequence[Adjustable]":
        return self.model.adjustables

    def restart(self) -> int:
        with pushd(self.job.workdir):
            starts = []
            for adjustable in self.adjustables:
                starts.append(adjustable.restart())
        if all(x == starts[0] for x in starts):
            # if everyone agrees on the iteration...
            logger.info("restart iteration from ", starts[0])
            return starts[0]
        else:
            return 0

    @property
    @abstractmethod
    def model(self) -> "Model":
        pass

    @property
    @abstractmethod
    def job(self) -> "JobMeta":
        pass

    def update_config(self, i: int, params: "DataFrame", id: str):
        """Update realization configuration file to execute BMI run at given iteration.

        parameters
        ---------
        i : Current iteration of calibration
        params : DataFrame containing the parameter name in `param` and value in `i` columns
        id : catchment id

        """
        return self.model.update_config(i, params, id, path=self.job.workdir)

    @property
    def best_params(self) -> str:
        return self.model.best_params


class Agent(BaseAgent):
    """This is class for agent."""

    def __init__(
        self,
        model_conf: dict,
        workdir: "Path",
        general: "General",
        log: bool = False,
        restart: bool = False,
        agent_counter=0,
        worker_name: str | None = None,
    ):
        """Construct attributes for the Agent class."""
        self._workdir = workdir
        self._job = None
        self._run_name = general.name
        self._params = general.strategy.parameters
        self._algorithm = general.strategy.algorithm.value
        self._yaml_file = general.yaml_file
        self._calib_path = general.calib_path
        self._valid_path = general.valid_path
        self._general = general
        self.run_single_iteration = False

        worker_prefix = (
            "ngen" if model_conf["type"] == "nocalib" else model_conf["type"]
        )
        
        if restart and "calib" in self._run_name:
            # find prior ngen workdirs
            # FIXME if a user starts with an independent calibration strategy
            # then restarts with a uniform strategy, this will "work" but probably shouldn't.
            # it works cause the independent writes a param df for the nexus that uniform also uses,
            # so data "exists" and it doesn't know its not conistent...
            # Conversely, if you start with uniform then try independent, it will start back at
            # 0 correctly since not all basin params can be loaded.
            # There are probably some similar issues with explicit and independent, since they have
            # similar data semantics
            workdirs = list(Path(workdir).rglob(worker_prefix + "_*_worker"))
            if len(workdirs) > 1 and self._algorithm == "pso":
                logger.warning("More than one existing {} workdir, cannot restart")
            else:
                self._job = JobMeta(worker_prefix, workdir, workdirs[agent_counter], log=log, worker_name=worker_name)

        if self._job is None:
            self._job = JobMeta(worker_prefix, workdir, log=log, worker_name=worker_name)

        if "calib" in self._run_name:
            self._calib_path_output = os.path.join(self._job.workdir, "Output_Calib")
            self._output_iter_path = os.path.join(self._job.workdir, "Output_Iteration")
            self._plot_iter_path = os.path.join(self._job.workdir, "Plot_Iteration")
            os.makedirs(self._calib_path_output, exist_ok=True)
            os.makedirs(self._output_iter_path, exist_ok=True)
            os.makedirs(self._plot_iter_path, exist_ok=True)

        if log and "valid" in self._run_name:
            self._valid_path_output = os.path.join(self._job.workdir, "Output_Valid")
            self._valid_path_plot = os.path.join(self._workdir, "Plot_Valid")
            if self._run_name not in ["valid_control", "valid_best"]:
                self._valid_path_plot = os.path.join(
                    self._workdir, "Plot_Valid" + self._run_name.replace("valid_", "_")
                )
            os.makedirs(self._valid_path_output, exist_ok=True)
            os.makedirs(self._valid_path_plot, exist_ok=True)
            self._calib_path_output = None
            self._output_iter_path = None
            self._plot_iter_path = None

        model_conf["workdir"] = self.job.workdir
        try:
            self._model = Model(model=model_conf)
        except ValidationError as e:
            print(f"validation error: {e.json()}")
            raise
        if not self.adjustables:
            logger.info("No calibratable parameters — activating single-run mode.")
            self.run_single_iteration = True

        self._model.model.resolve_paths()
        self.nwmflow_file = ""

    @property
    def parameters(self) -> "Mapping[str, Any]":
        return self._params

    @property
    def workdir(self) -> "Path":
        return self._workdir

    @property
    def job(self) -> "JobMeta":
        return self._job

    @property
    def model(self) -> "Model":
        return self._model.model

    @property
    def cmd(self) -> str:
        """Proxy method to build command from contained model binary and args."""
        return "{} {}".format(self.model.get_binary(), self.model.get_args())

    def create_valid_cmd(self, valid_config_file) -> str:
        """Build command for validation run."""
        arg1 = self.model.catchments.resolve()
        arg2 = self.model.nexus.resolve()
        valid_args = '{} "all" {} "all" {}'.format(arg1, arg2, valid_config_file)

        return "{} {}".format(self.model.get_binary(), valid_args)

    @property
    def calib_path(self) -> "Path":
        """Directory for calibration run."""
        return self._calib_path

    @property
    def calib_path_output(self) -> "Path":
        """Directory for calibration output."""
        return self._calib_path_output

    @property
    def output_iter_path(self) -> "Path":
        """Directory for output at each calibration iteartion."""
        return self._output_iter_path

    @property
    def plot_iter_path(self) -> "Path":
        """Directory for plots at each calibration iteartion"""
        return self._plot_iter_path

    @property
    def valid_path(self) -> "Path":
        """Directory for output files of validation run."""
        return self._valid_path

    @property
    def valid_path_output(self) -> "Path":
        """Directory for output files of validation run."""
        return self._valid_path_output

    @property
    def valid_path_plot(self) -> "Path":
        """Directory for plots of validation run."""
        return self._valid_path_plot

    @property
    def algorithm(self) -> str:
        """Optimization algorithm."""
        return self._algorithm

    @property
    def run_name(self) -> "Path":
        """Calibration or validation run."""
        return self._run_name

    @property
    def yaml_file(self) -> "Path":
        """Calibration yaml file."""
        return self._yaml_file

    @property
    def model_params(self) -> dict:
        """Model calibration parameters."""
        return self.model.model_params

    @property
    def realization_file(self) -> "Path":
        """Model realization file."""
        return self.model.realization_file

    def duplicate(self, restart_flag=False, agent_counter=0) -> "Agent":
        """Create a duplicate agent with independent workspace"""
        # Create minimal model config just to create worker
        # TODO: This reinitializes the NgenUniform/NgenGrouped code for each particle in PSO, which isn't efficient
        minimal_model = {
            "type": self.model.model_type,
            "strategy": self.model.model_strategy,
            "catchments": self.model.strategy.catchments,
            "params": self.model.strategy.params,
            "nexus": self.model.strategy.nexus,
            "crosswalk": self.model.strategy.crosswalk,
            "realization": self.model.strategy.realization
        }

        # Create new agent with minimal model
        new_agent = Agent(
            minimal_model,
            self._workdir,
            self._general,
            log=False,
            restart=restart_flag,
            agent_counter=agent_counter
        )

        # Replace model with shared reference to original model
        new_agent._model = self._model

        return new_agent
