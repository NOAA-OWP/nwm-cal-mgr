"""
This module contains methods to process simulation output during model execution.

@author: Xia Feng, Nels Frazer
"""

import copy
import glob
import json
import os
import shutil
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Union

try:  # to get literal in python 3.7, it was added to typing in 3.8
    from typing import Literal
except ImportError:
    from typing_extensions import Literal

import ewts
import pandas as pd
import yaml
from pydantic import (
    BaseModel,
    DirectoryPath,
    Field,
    conint,
    field_validator,
)
from pydantic.types import ImportString

from .strategy import Objective

import ewts
from common import get_calmgr_logger
logger = get_calmgr_logger()


# additional constrained types
PosInt = conint(gt=-1)


class Configurable(ABC):
    """Abstract interface for wrapping configurable external models."""

    @abstractmethod
    def get_binary() -> str:
        """Get the binary string to execute.

        Returns:
            str: The binary name or path used to execute the Configurable model
        """

    @abstractmethod
    def get_args() -> str:
        """Get the args to pass to the binary

        Returns:
            str: Preconfigured arg string to pass to the binary upon execution
        """

    @abstractmethod
    def update_config(*args, **kwargs):
        pass


class EvaluationOptions(BaseModel):
    """A class for performance evaluation and output processing during model run."""

    evaluation_start: Optional[datetime] = None
    evaluation_stop: Optional[datetime] = None
    _eval_range: Tuple[datetime, datetime] = None
    valid_start_time: Optional[datetime] = None
    valid_end_time: Optional[datetime] = None
    valid_eval_start_time: Optional[datetime] = None
    valid_eval_end_time: Optional[datetime] = None
    full_eval_start_time: Optional[datetime] = None
    full_eval_end_time: Optional[datetime] = None
    _valid_range: Tuple[datetime, datetime] = None
    _valid_eval_range: Tuple[datetime, datetime] = None
    _full_eval_range: Tuple[datetime, datetime] = None
    objective: Optional[Union[Objective, ImportString]] = Objective.kge
    target: Union[Literal["min"], Literal["max"], float] = "min"
    objfunc_str: Optional[str] = "1-KGE"
    _best_score: float
    _best_params_iteration: str = "0"
    _best_save_flag: bool = None
    id: Optional[str] = None
    basinID: Optional[str] = None
    threshold_categorical: Optional[dict] = {"value": 0.9, "type": "quantile"}
    threshold_event: Optional[dict] = {"value": 0.9, "type": "quantile"}
    site_name: Optional[str] = None
    streamflow_name: Optional[str] = "sim_flow"
    save_output_iteration: Optional[bool] = False
    save_plot_iteration: Optional[bool] = False
    save_plot_iter_freq: Optional[int] = 50
    user: Optional[str] = None
    _objective_log_file: Path
    _metric_iter_file: Path
    _param_iter_file: Path
    _param_all_file: Path
    _output_iter_file: Path
    _last_output_file: Path
    _best_output_file: Path
    _last_iter_file: Path
    _cost_iter_file: Path

    class Config:
        """Override configuration for pydantic BaseModel."""

        # underscore_attrs_are_private = True
        use_enum_values = (
            False  # if true, then objective turns into a str, and things blow up
        )

    def __init__(self, **kwargs):
        """Assign output files, evaluation time range, and initialize best obejctive function and best iteration."""
        super().__init__(**kwargs)
        self._objective_log_file = kwargs.pop(
            "objective_log_file", Path("{}_objective_log.txt".format(self.basinID))
        )
        self._metric_iter_file = kwargs.pop(
            "metric_iter_file", Path("{}_metrics_iteration.csv".format(self.basinID))
        )
        self._param_iter_file = kwargs.pop(
            "param_iter_file", Path("{}_params_iteration.csv".format(self.basinID))
        )
        self._param_all_file = kwargs.pop(
            "param_all_file", Path("{}_params_all.csv".format(self.basinID))
        )
        self._output_iter_file = kwargs.pop(
            "output_iter_file", Path("{}_output_iteration_".format(self.basinID))
        )
        self._last_output_file = kwargs.pop(
            "last_output_file",
            Path("{}_output_last_iteration.csv".format(self.basinID)),
        )
        self._best_output_file = kwargs.pop(
            "best_output_file",
            Path("{}_output_best_iteration.csv".format(self.basinID)),
        )
        self._last_iter_file = kwargs.pop(
            "last_iter_file", Path("{}_last_iteration.csv".format(self.basinID))
        )
        self._cost_iter_file = kwargs.pop(
            "cost_iter_file", Path("{}_cost_iter.csv".format(self.basinID))
        )

        if self.evaluation_start and self.evaluation_stop:
            self._eval_range = (self.evaluation_start, self.evaluation_stop)
        else:
            self._eval_range = None
        if self.valid_start_time and self.valid_end_time:
            self._valid_range = (self.valid_start_time, self.valid_end_time)
        else:
            self._valid_range = None
        if self.valid_eval_start_time and self.valid_eval_end_time:
            self._valid_eval_range = (
                self.valid_eval_start_time,
                self.valid_eval_end_time,
            )
        else:
            self._valid_eval_range = None
        if self.full_eval_start_time and self.full_eval_end_time:
            self._full_eval_range = (self.full_eval_start_time, self.full_eval_end_time)
        else:
            self._full_eval_range = None
        if self.target == "max":
            self._best_score = float("-inf")
        else:
            self._best_score = float("inf")
        self._best_params_iteration = "0"  # String representation of interger iteration

    def update(self, i: int, score: float, log: bool, algorithm: str) -> None:
        """Update the meta state for iteration `i`

        Parameters
        ----------
        i : Current iteration
        score : Objecfive function
        log : If True, save objective function at each iteration.
        algorithm : Optimization algorithm

        """
        if os.path.exists(self._objective_log_file) and algorithm != "dds":
            df_log = pd.read_csv(self._objective_log_file).tail(1)
            self._best_params_iteration = str(df_log.iloc[0]["best_iteration"])
            self._best_score = df_log.iloc[0]["best_objective_function"]

        if self.target == "min":
            if score <= self._best_score:
                self._best_params_iteration = str(i)
                self._best_score = score
                self._best_save_flag = True
            else:
                self._best_save_flag = False
        elif self.target == "max":
            if score >= self._best_score:
                self._best_params_iteration = str(i)
                self._best_score = score
                self._best_save_flag = True
            else:
                self._best_save_flag = False
        else:
            if abs(score - self.target) <= abs(self._best_score - self.target):
                self._best_params_iteration = str(i)
                self._best_score = score
                self._best_save_flag = True
            else:
                self._best_save_flag = False
        if log:
            self.write_objective_log_file(i, score)

    def write_objective_log_file(self, i: int, score: float) -> None:
        """Write objective funtion and iteration into csv file.

        Parameters
        ----------
        i : iteration
        score : objecfive function

        """
        if not os.path.exists(self._objective_log_file):
            with open(self._objective_log_file, "w") as log_file:
                log_file.writelines(
                    [
                        "iteration,",
                        "objective_function,",
                        "best_iteration,",
                        "best_objective_function\n",
                    ]
                )
        with open(self._objective_log_file, "a+") as log_file:
            log_file.writelines(
                [
                    "{}, ".format(i),
                    "{}, ".format(score),
                    "{}, ".format(self._best_params_iteration),
                    "{}\n".format(self._best_score),
                ]
            )

    def write_metric_iter_file(self, i: int, score: float, metrics: float) -> None:
        """Write statistical metrics at each iteration into csv file.

        Parameters
        ----------
        i : iteration
        metrics : statistical metrics

        """
        metric_current = {"iteration": i, "objFunVal": score}
        metric_current.update(metrics)
        metric_current = pd.DataFrame([metric_current])
        metric_current.to_csv(
            self._metric_iter_file,
            mode="a",
            index=False,
            header=not os.path.exists(self._metric_iter_file),
        )

    def write_param_iter_file(self, i: int, params: "DataFrame") -> None:
        """Write calibrated parameters at each iteration into csv file.

        Parameters
        ----------
        i : iteration
        params : DataFrame with optimized parameters at each iteration

        """
        param_current = params.copy()
        param_current["iteration"] = i
        param_order = param_current.param
        param_current = param_current.pivot_table(
            index="iteration", columns="param", values=str(i)
        )
        param_current = param_current[param_order]
        param_current.reset_index(inplace=True)
        param_current.to_csv(
            self._param_iter_file,
            mode="a",
            index=False,
            header=not os.path.exists(self._param_iter_file),
        )

    def write_param_all_file(self, i: int, params: "DataFrame") -> None:
        """Write calibrated parameters at each iteration alongside original min/max values into csv file.

        Parameters
        ----------
        i : iteration
        params : DataFrame with optimized parameters at each iteration

        """
        df_params = params.copy()
        df_params.pop("model")
        param_name = df_params["param"]
        df_params.drop("param", axis=1, inplace=True)
        df_params = df_params.T.rename(
            columns=dict(zip(df_params.T.columns, param_name))
        )

        # Remove rows for plotting
        df_params.reset_index(inplace=True)
        if os.path.exists(self._param_all_file):
            df_params = df_params.tail(1)

        df_params.to_csv(
            self._param_all_file,
            mode="a",
            index=False,
            header=not os.path.exists(self._param_all_file),
        )

    def write_last_iteration(self, i: int) -> None:
        """Write completed iteration into csv file.

        Parameters
        ----------
        i : iteration

        """
        if not os.path.exists(self._last_iter_file):
            with open(self._last_iter_file, "w") as log_file:
                log_file.writelines(["site_no,", "last_iteration\n"])
        with open(self._last_iter_file, "a+") as log_file:
            log_file.writelines(["{}, ".format(self.basinID), "{} \n".format(i)])

    def write_cost_iter_file(self, i: int, calib_run_path: Path) -> Path:
        """Write global best cost function at each iteration into csv file.

        Parameters
        ----------
        i : iteration
        calib_run_path : directory for calibration run

        Returns:
        ----------
        cost_iter_file : Path

        """
        cost_iter_file = os.path.join(calib_run_path, self._cost_iter_file)

        obj_file = glob.glob(
            os.path.join(calib_run_path, "ngen*", "*objective_log.txt")
        )
        df_log = pd.DataFrame()
        for f in obj_file:
            alog = pd.read_csv(f)
            df_log = pd.concat([df_log, alog], ignore_index=True)

        df_cost = pd.DataFrame()
        for n in range(0, i + 1):
            df_log_iter = df_log.query("iteration==@n")[
                ["iteration", "best_objective_function"]
            ]
            if df_log_iter.shape[0] > 0:
                best_cost = pd.DataFrame(
                    {
                        "iteration": n,
                        "global_best": df_log_iter["best_objective_function"].min(),
                    },
                    index=[0],
                )
                df_cost = pd.concat([df_cost, best_cost], ignore_index=True)

        if df_cost.shape[0] == i + 1 and df_log.shape[0] == len(obj_file) * i + 1:
            df_cost.to_csv(cost_iter_file, index=False)

        return cost_iter_file

    def write_hist_file(
        self, optimizer_result: "SwarmOptimizer", agent: "Agent", params: "pd.DataFrame"
    ) -> Path:
        """Write cost and position history plus global best position into csv files.

        Parameters
        ----------
        optimizer_result : SwarmOptimizer object
        agent : Agent object
        params_lst : Calibration parameter list

        Returns:
        ----------
        cost_hist_file : Path

        """
        # Save best cost
        cost_hist = {
            "iteration": range(1, len(optimizer_result.cost_history) + 1),
            "global_best": optimizer_result.cost_history,
            "mean_local_best": optimizer_result.mean_pbest_history,
        }
        if agent.algorithm == "gwo":
            cost_hist.update({"mean_leader_best": optimizer_result.mean_leader_history})
        cost_hist = pd.DataFrame(cost_hist)
        cost_hist_file = os.path.join(
            agent.workdir, "{}_cost_hist.csv".format(self.basinID)
        )
        cost_hist.to_csv(cost_hist_file, index=False)

        # Save parameters of swarms
        pos_hist = pd.DataFrame()
        for i in range(len(optimizer_result.pos_history)):
            pos_df = pd.DataFrame(
                optimizer_result.pos_history[i], columns=params["param"].tolist()
            )
            pos_df["agent"] = range(1, optimizer_result.swarm.n_particles + 1)
            pos_df["iteration"] = i + 1
            pos_hist = pd.concat([pos_hist, pos_df], ignore_index=True)
        pos_hist_file = os.path.join(
            agent.workdir, "{}_pos_hist.csv".format(self.basinID)
        )
        pos_hist.to_csv(pos_hist_file, index=False)

        # Save best parameters
        best_pos = pd.DataFrame(
            optimizer_result.swarm.best_pos, columns=["global_best_params"]
        )
        best_pos.reset_index(inplace=True, drop=True)
        best_pos["param"] = params["param"].tolist()
        best_pos["model"] = params["model"].tolist()
        # best_pos['param'] = params_lst
        # best_pos['model'] = list(agent.model_params.keys())*len(best_pos)
        # def flatten(xss):
        #    return [x for xs in xss for x in xs]
        # best_pos['model'] = flatten([[m1]*len(agent.model_params[m1]) for m1 in agent.model_params.keys()])

        best_pos_file = os.path.join(
            agent.workdir, "{}_global_best_params.csv".format(self.basinID)
        )
        best_pos.to_csv(best_pos_file, index=False)

        # Save local and leader best
        if agent.algorithm == "gwo":
            pbest_hist = pd.DataFrame()
            for i in range(len(optimizer_result.pbest_history)):
                pbest_df = pd.DataFrame(
                    optimizer_result.pbest_history[i], columns=["local_best"]
                )
                pbest_df["agent"] = range(1, optimizer_result.swarm.n_particles + 1)
                pbest_df["iteration"] = i + 1
                pbest_hist = pd.concat([pbest_hist, pbest_df], ignore_index=True)
            pbest_hist_file = os.path.join(
                agent.workdir, "{}_pbest_hist.csv".format(self.basinID)
            )
            pbest_hist.to_csv(pbest_hist_file, index=False)
            leader_hist = pd.DataFrame()
            for i in range(len(optimizer_result.leader_history)):
                leader_df = pd.DataFrame(
                    optimizer_result.leader_history[i], columns=["leader_best"]
                )
                leader_df["rank"] = range(1, 4)
                leader_df["iteration"] = i + 1
                leader_hist = pd.concat([leader_hist, leader_df], ignore_index=True)
            leader_hist_file = os.path.join(
                agent.workdir, "{}_leader_hist.csv".format(self.basinID)
            )
            leader_hist.to_csv(leader_hist_file, index=False)

        return cost_hist_file

    def write_run_complete_file(self, run_name: str, path: "Path") -> None:
        """Write empty file if calibration or validation run is complete.

        Parameters
        ----------
        path : directory to save file
        run_name : calib, control or best run

        """
        complete_file = os.path.join(
            path,
            "{}".format(self.basinID)
            + "_"
            + "{}".format(run_name).capitalize()
            + "_Run_Complete",
        )
        with open(complete_file, "w") as fp:
            pass

    @property
    def best_score(self) -> float:
        """Best objective function."""
        return self._best_score

    @property
    def best_params(self) -> str:
        """The best iteration."""
        return self._best_params_iteration

    @property
    def objective_log_file(self) -> Path:
        """The path of the best objective function log file."""
        if id is not None:
            prefix = ""
        else:
            prefix = f"{self.id}_"
        return Path(
            self._objective_log_file.parent,
            prefix + self._objective_log_file.stem + self._objective_log_file.suffix,
        )

    @property
    def output_iter_file(self) -> Path:
        """Output file at each iteration."""
        return self._output_iter_file

    @property
    def last_output_file(self) -> Path:
        """Output file at last iteration."""
        return self._last_output_file

    @property
    def best_output_file(self) -> Path:
        """Output file at best iteration."""
        return self._best_output_file

    @property
    def metric_iter_file(self) -> Path:
        """File to store metrics at each iteration."""
        return self._metric_iter_file

    @property
    def param_iter_file(self) -> Path:
        """File to store calibrated parameters at each iteration."""
        return self._param_iter_file

    @property
    def cost_iter_file(self) -> Path:
        """File to store global and local best cost function at each iteration."""
        return self._cost_iter_file

    @property
    def best_save_flag(self) -> bool:
        """Whether save output file at each iteration."""
        return self._best_save_flag

    @property
    def save_output_iter_flag(self) -> bool:
        """Whether save output file at each iteration."""
        return self.save_output_iteration

    @property
    def save_plot_iter_flag(self) -> bool:
        """Whether save plot file at each iteration."""
        return self.save_plot_iteration

    @field_validator("objective")
    def validate_objective(cls, value):
        if value is None:
            logger.info("Objective cannot be none -- setting default objective")
            value = Objective.kge
        return value

    def read_objective_log_file(self) -> dict:
        """Read objective function log file.

        Returns
        ----------
        current iteration, best iteration, best objective function

        """
        df_obj = pd.read_csv(str(self._objective_log_file))
        iteration = df_obj.iloc[-1]["iteration"]
        best_params = df_obj.iloc[-1]["best_iteration"]
        best_score = df_obj.iloc[-1]["best_objective_function"]
        return {
            "iteration": iteration,
            "best_iteration": best_params,
            "best_score": best_score,
        }

    def organize_file_for_restart(self, i: int) -> dict:
        """Create copies for files of storing objective function, metrics, and parameters at each iteration,
        remove the records from the last completed or unfinished iteration and save the remaining records into new files.

        Parameters
        ----------
        i : last iteration

        """
        # Creat copies for iteration files and clean up
        all_log_files = [
            str(self._objective_log_file),
            str(self._metric_iter_file),
            str(self._param_iter_file),
        ]
        for infile in all_log_files:
            shutil.copy(
                infile, infile + "_before_restart_" + time.strftime("%Y%m%d_%H%M%S")
            )
            indata = pd.read_csv(infile)
            if indata.iloc[-1]["iteration"] == i:
                indata.iloc[0 : (len(indata) - 1)].to_csv(infile, index=False)
            elif (
                indata.iloc[-1]["iteration"] - i == 1
                and indata.iloc[-2]["iteration"] == i
            ):
                indata.iloc[0 : (len(indata) - 2)].to_csv(infile, index=False)

    def restart(self) -> int:
        """
        Restart calibration run from the last completed iteration

        Returns
        ----------
        start_iteration: iteration to restart calibration

        """
        df_iter = pd.read_csv(self._last_iter_file, dtype=object)
        start_iteration = int(df_iter.iloc[-1]["last_iteration"])
        shutil.copy(
            str(self._last_iter_file),
            str(self._last_iter_file)
            + "_before_restart_"
            + time.strftime("%Y%m%d_%H%M%S"),
        )
        df_iter.iloc[0 : (len(df_iter) - 1)].to_csv(self._last_iter_file, index=False)

        self.organize_file_for_restart(start_iteration)

        df_obj = self.read_objective_log_file()
        self._best_params_iteration = str(df_obj["best_iteration"])
        self._best_score = df_obj["best_score"]

        return start_iteration


class ModelExec(BaseModel, Configurable):
    """
    The data class for a given model, which must also be Configurable
    """

    binary: str
    args: Optional[str] = None
    workdir: DirectoryPath = Path("./")  # FIXME test the various workdirs
    eval_params: Optional[EvaluationOptions] = Field(default_factory=EvaluationOptions)

    # FIXME formalize type: str = "ModelName"
    def get_binary(self) -> str:
        """Get the binary string to execute

        Returns:
            str: The binary name or path used to execute the Configurable model
        """
        return self.binary

    def get_args(self) -> str:
        """Get the args to pass to the binary

        Returns:
            str: Preconfigured arg string to pass to the binary upon execution
        """
        return self.args

    def run(self, args: str = None) -> None:
        """
        Execute the model binary with arguments in the specified working directory.
        """
        import subprocess

        cmd = [self.binary]
        if args:
            cmd.extend(args.split())
        elif self.args:
            cmd.extend(self.args.split())

        logger.info(f"Executing model: {' '.join(cmd)} in {self.workdir}")
        subprocess.run(cmd, cwd=self.workdir, check=True)
