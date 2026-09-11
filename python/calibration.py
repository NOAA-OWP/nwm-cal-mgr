"""
This is the main script to read calibration configuration file and execute calibration run.

The high-level path through the code
- cli() parses args, initializes the logger, loads YAML config, creates General, 
  changes into the workdir, then calls main(...)
- main() creates an Agent, determines which algorithm is being used, 
  sets start_iteration, and chooses the search (search.py) function:
    dds_set
    pso_search
    gwo_search
    or single_exec for no-calibration runs.
- That selected search function performs the iterative calibration loop.

@author: Yuqiong Liu. Inital source: ngen-cal from Nels Frazer Xia Feng
"""
import pprint
import argparse
import os
from pathlib import Path

import yaml

import ewts

LOG = ewts.logger.get_logger(ewts.CAL_MGR_ID)

from calib import General
from calib.agent import Agent
from calib.configuration import NoCalibModel
from calib.search import dds_set, pso_search, gwo_search, single_exec
from calib.strategy import Algorithm
from calib.utils import set_os_env_key, OS_ENV_KEY_RESULTS_DIR, OS_ENV_KEY_NGEN_LOG_FILE_PREFIX
from calib.git_util import print_git_info_all

from common import (
    str_to_bool,
    initialize_logger,
    build_calibration_log_file_name,
)


def main(
        general: General,
        model_conf,
        log_path_overwrite: str | None = None,
        worker_name: str | None = None,
        log_level_override: str | None = None,
        log_file_name_override: str | None = None,
        enabled_override: bool | None = None
    ):
    global LOG

    print_git_info_all()

    """
    If worker_name is not provided, a random string will be used when generating the worker directory.
    The random string is necessary when running non-DDS algorithms, since those leverage multiple workers.
    Therefore, worker_name should not be provided (or should be None) when using any algorithm besides DDS.
    """
    if worker_name is not None and general.strategy.algorithm != Algorithm.dds:
        msg = f"Static worker_name provision is only compatible with algorithm {Algorithm.dds}, but algorithm {general.strategy.algorithm} was provided."
        LOG.fatal(msg)
        raise ValueError(msg)

    # Seed the random number generators if requested
    if general.random_seed is not None:
        import random

        random.seed(general.random_seed)
        import numpy as np

        np.random.seed(general.random_seed)

    """
    TODO calibrate each "catcment" independely, but there may be something interesting in grouping various formulation params
    into a single variable vector and calibrating a set of heterogenous formultions...
    """
    start_iteration = 0

    # Initialize the starting agent
    agent = Agent(model_conf, general.calib_path, general, general.log, general.restart, worker_name=worker_name)

    if log_path_overwrite is None:
        LOG.info("Calibration bootstrap complete. Switching to calibration job log.")

        job_log_dir = Path(agent.workdir)
        job_log_file_name = build_calibration_log_file_name(
            calibration_run_id=general.calibration_run_id,
            bootstrap=False,
        )

        LOG = initialize_logger(
            enabled_override=enabled_override,
            log_path_overwrite=None,
            log_file_name_override=log_file_name_override or job_log_file_name,
            log_level_override=log_level_override,
            reset_file=True,
            default_log_dir=job_log_dir,
        )

    # set environment variables for ngencerf backend and ngen runs
    print(f"ngen env var {OS_ENV_KEY_RESULTS_DIR} set to {agent.workdir}",flush=True)
    print(f"ngen env var {OS_ENV_KEY_NGEN_LOG_FILE_PREFIX} set to ngen_calib",flush=True)
    set_os_env_key(
        OS_ENV_KEY_RESULTS_DIR, str(Path(agent.workdir)), override=False
    )
    set_os_env_key(
        OS_ENV_KEY_NGEN_LOG_FILE_PREFIX, "calib", override=False
    )

    LOG.info("Starting calib")

    import numpy as np

    if general.strategy.algorithm == Algorithm.dds:
        start_iteration = general.start_iteration
        if general.restart:
            start_iteration = agent.restart()
        func = dds_set  # FIXME what about explicit/dds
    elif general.strategy.algorithm == Algorithm.pso:  # TODO how to restart PSO?
        if agent.model.strategy.strategy not in ["uniform", "grouped"]:
            LOG.warning("Can only use PSO with the uniform or grouped model strategy")
            return
        if general.restart:
            LOG.warning("Restart not supported for PSO search, starting at 0")
        func = pso_search
    elif general.strategy.algorithm == Algorithm.gwo:
        if agent.model.strategy.strategy not in ["uniform", "grouped"]:
            LOG.warning("Can only use GWO with the uniform or grouped model strategy")
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

    elif agent.model.strategy.strategy == "grouped":
        func(start_iteration, general.iterations, agent)


def cli():
    """Command-line interface entry point for nwm-calibration."""
    parser = argparse.ArgumentParser(
        description="Calibrate catchments in NGEN architecture."
    )
    parser.add_argument(
        "config_file",
        type=Path,
        help="The configuration yaml file for catchments to be operated on",
    )
    parser.add_argument("--log_path_overwrite", required=False, type=str, help="""
        If provided, this file path will be used for logging. If a filename, the file will be overwritten.
        If not provided, a log file path will be decided by the program.""")
    parser.add_argument("--logging_enabled", type=str_to_bool, default=True, help="""
        Enable or disable cal-mgr logging (default=enabled).
        Accepts: true/false, yes/no, on/off, 1/0."""
    )
    parser.add_argument("--log_file_name", required=False, type=str, help="""
        If provided, this file name will be used for cal-mgr logging, otherwise it will be decided by the program.""")
    parser.add_argument("--log_level", required=False, type=str, help="""
        If provided, this log level will be used for cal-mgr logging. (default=INFO).""")
    parser.add_argument(
        "--worker_name",
        required=False,
        type=str,
        help="""If provided, the worker directory will use this static prefix (for development, not for production environment).
        If not provided, the worker directory will include a random string, to support concurrent runs.""",
    )
    args = parser.parse_args()

    with open(args.config_file) as file:
        conf = yaml.safe_load(file)

    general_conf = conf["general"]
    workdir = Path(general_conf["workdir"])
    default_log_dir = workdir / "logs"
    calibration_run_id = general_conf.get("calibration_run_id")

    global LOG

    if args.log_path_overwrite is not None:
        job_log_file_name = build_calibration_log_file_name(
            calibration_run_id=calibration_run_id,
            bootstrap=False,
        )

        LOG = initialize_logger(
            enabled_override=args.logging_enabled,
            log_path_overwrite=args.log_path_overwrite,
            log_file_name_override=args.log_file_name or job_log_file_name,
            log_level_override=args.log_level,
            reset_file=True,
            default_log_dir=default_log_dir,
        )
    else:
        bootstrap_log_file_name = build_calibration_log_file_name(
            calibration_run_id=calibration_run_id,
            bootstrap=True,
        )

        LOG = initialize_logger(
            enabled_override=args.logging_enabled,
            log_path_overwrite=None,
            log_file_name_override=args.log_file_name or bootstrap_log_file_name,
            log_level_override=args.log_level,
            reset_file=True,
            default_log_dir=default_log_dir,
        )

        LOG.info("Calibration bootstrapping started")

    general = General(**conf["general"])
    os.chdir(general.workdir)

    main(
        general,
        conf["model"],
        log_path_overwrite=args.log_path_overwrite,
        worker_name=args.worker_name,
        log_level_override=args.log_level,
        log_file_name_override=args.log_file_name,
        enabled_override=args.logging_enabled,
    )


if __name__ == "__main__":
    cli()
