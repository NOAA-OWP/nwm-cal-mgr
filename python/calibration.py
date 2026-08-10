"""
This is the main script to read calibration configuration file and execute calibration run.

@author: Nels Frazer and Xia Feng
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from calib import General
from calib.agent import Agent
from calib.configuration import NoCalibModel
from calib.git_util import print_git_info_all
from calib.search import dds_set, pso_search, gwo_search, single_exec
from calib.strategy import Algorithm

LOG = logging.getLogger(__name__)


def create_timestamp() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]


def log_level_set(log_path_overwrite: str | None = None):
    """
    Set logging level and specify logger configuration.

    Arguments
    ---------
    log_path_overwrite (str | None) (optional):
        Log file path to write to. File will be overwritten.
        If not provided, the program will decide a log file path on the fly.

    Returns
    -------
    None

    Notes
    -----
    In the absense of user-specified logging level, level defaults to DEBUG
    See also https://docs.python.org/3/library/logging.html

    """

    log_level = "DEBUG"
    if True:
        if log_path_overwrite:
            logFilePath = log_path_overwrite
            print(f"log_path_overwrite = {repr(log_path_overwrite)}, deleting file if already exists, to start a new log file")
            try:
                os.remove(logFilePath)
            except FileNotFoundError:
                pass
            os.makedirs(os.path.dirname(logFilePath), exist_ok=True)

        else:
            BASE_DIR = Path(__file__).resolve().parent.parent

            if Path("/ngencerf/data").exists():
                log_file_dir = Path(
                    f"/ngencerf/data/run-logs/ngen_cal_{create_timestamp()}/"
                )
            else:
                log_file_dir = Path(BASE_DIR) / f"run-logs/ngen_cal_{create_timestamp()}/"

            log_file_name = "ngen_cal.log"
            os.makedirs(log_file_dir, exist_ok=True)
            logFilePath = os.path.join(log_file_dir, log_file_name)

            try:
                logFile = open(logFilePath, "a")
                print(f"Logging into: {logFilePath}")
            except IOError:
                print(
                    f"Can't Open local directory Log File: {logFilePath}", file=sys.stderr
                )

        logging.Formatter.converter = time.gmtime
        logging.basicConfig(
            force=True,
            level=log_level,
            format="%(asctime)s.%(msecs)03d NGEN_CAL %(levelname)s    %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
            handlers=[
                logging.FileHandler(logFilePath, mode="a"),  # Log to a file
                logging.StreamHandler(sys.stdout),
            ],
        )
    else:
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)s - %(funcName)s]: %(message)s",
            stream=sys.stderr,
        )


def main(general: General, model_conf, log_path_overwrite: str | None = None):
    # Seed the random number generators if requested
    if general.random_seed is not None:
        import random

        random.seed(general.random_seed)
        import numpy as np

        np.random.seed(general.random_seed)

    # setup logging
    log_level_set(log_path_overwrite=log_path_overwrite)

    LOG.info("Starting calib")

    """
    TODO calibrate each "catcment" independely, but there may be something interesting in grouping various formulation params
    into a single variable vector and calibrating a set of heterogenous formultions...
    """
    start_iteration = 0

    # Initialize the starting agent
    agent = Agent(model_conf, general.calib_path, general, general.log, general.restart)

    # set environment variable for ngencerf backend
    os.environ["NGEN_RESULTS_DIR"] = str(Path(agent.workdir).parent.parent)
    logging.info(
        f"Set environment variable NGEN_RESULTS_DIR to: {os.environ['NGEN_RESULTS_DIR']}"
    )

    import numpy as np

    if general.strategy.algorithm == Algorithm.dds:
        start_iteration = general.start_iteration
        if general.restart:
            start_iteration = agent.restart()
        func = dds_set  # FIXME what about explicit/dds
    elif general.strategy.algorithm == Algorithm.pso:  # TODO how to restart PSO?
        if agent.model.strategy.strategy != "uniform":
            LOG.warning("Can only use PSO with the uniform model strategy")
            return
        if general.restart:
            LOG.warning("Restart not supported for PSO search, starting at 0")
        func = pso_search
    elif general.strategy.algorithm == Algorithm.gwo:
        if agent.model.strategy.strategy != "uniform":
            LOG.warning("Can only use GWO with the uniform model strategy")
            return
        if general.restart:
            start_iteration = agent.restart()
        func = gwo_search

    LOG.info("Starting Iteration: {}".format(start_iteration))
    LOG.info("Starting calibration loop")
    if general.strategy.algorithm in [Algorithm.pso, Algorithm.gwo]:
        LOG.info(
            f"The full set of plots are only produced for the first worker at: {agent.job.workdir}"
        )

    # NOTE this assumes we calibrate each catchment independently, it may be possible to design an "aggregate" calibration
    # that works in a more sophisticated manner.
    if isinstance(agent.model, NoCalibModel):
        LOG.info("Running Single Execution Model Calibration (NoCalibModel)")
        single_exec(agent)

        LOG.info("Calibration complete.")
    # FIXME this needs a refactor...should be able to use a calibration_set with explicit loading
    elif agent.model.strategy.strategy == "explicit":
        for catchment in agent.model.adjustables:
            dds(start_iteration, general.iterations, catchment, agent)

    elif agent.model.strategy.strategy == "independent":
        # for catchment_set in agent.model.adjustables:
        func(start_iteration, general.iterations, agent)

    elif agent.model.strategy.strategy == "uniform":
        func(start_iteration, general.iterations, agent)


def cli():
    """Command-line interface entry point for nwm-calibration."""
    print_git_info_all()

    # Create the command line parser
    parser = argparse.ArgumentParser(
        description="Calibrate catchments in NGEN architecture."
    )
    parser.add_argument(
        "config_file",
        type=Path,
        help="The configuration yaml file for catchments to be operated on",
    )
    parser.add_argument("--log_path_overwrite", required=False, type=str, help="""
        If provided, this file path will be used for logging (the file will be overwritten).
        If not provided, a log file path will be decided by the program.""")

    args = parser.parse_args()

    with open(args.config_file) as file:
        conf = yaml.safe_load(file)

    general = General(**conf["general"])

    # Change directory to workdir
    os.chdir(general.workdir)

    main(general, conf["model"], log_path_overwrite=args.log_path_overwrite)


if __name__ == "__main__":
    cli()
