"""
This is the main script to read calibration configuration file and create inputs files needed for
validation run with an alternative parameter set

@author: Yuqiong Liu
"""

import argparse
import ewts
import json
import os
import shutil
from pathlib import Path

import pandas as pd
import yaml
from calib.agent import Agent
from calib.configuration import General
from calib.utils import set_os_env_key, OS_ENV_KEY_RESULTS_DIR, OS_ENV_KEY_NGEN_LOG_FILE_PREFIX
from calib.validation_run import run_valid_ctrl_best
from mswm.edit_config import create_valid_realization_file
from calib.git_util import print_git_info_all

from common import (
    str_to_bool,
    initialize_logger,
    build_validation_log_file_name,
)

LOG = ewts.logger.get_logger(ewts.CAL_MGR_ID)


def main(
        general: General,
        model_conf, 
        worker: str,
        iteration: int,
        log_path_overwrite: str | None = None,
        log_level_override: str | None = None,
        log_file_name_override: str | None = None,
        enabled_override: bool | None = None
):
    global LOG

    print_git_info_all()

    # Initialize agent
    agent = Agent(model_conf, general.valid_path, general, general.log, general.restart)

    print(f'\nagent.algorithm={agent.algorithm}', flush=True)

    # read the parameter values from the *params_iteration.csv file
    file1 = Path(
        agent.calib_path,
        "ngen_" + worker + "_worker",
        model_conf["eval_params"]["basinID"] + "_params_iteration.csv",
    )
    if not os.path.exists(file1):
        raise FileNotFoundError("File does not exist: " + str(file1))
    df1 = pd.read_csv(file1).set_index("iteration")
    df1 = pd.DataFrame(df1.loc[iteration])

    # write the realization and config files for validation run
    calibration_sets = agent.model.adjustables

    # params_iteration contains parameter values for all formulation groups
    param_values_all = df1[iteration].to_list()

    idx = 0
    group_adfs = []
    for calibration_set in calibration_sets:
        group_dims = len(calibration_set.adjustables[0].adf)
        param_values = param_values_all[idx:idx + group_dims]
        idx += group_dims

        # Get iteration parameter values for this group
        calibration_object = calibration_set.adjustables[0]
        calibration_object.adf.loc[:, general.name] = param_values
        group_adfs.append(calibration_object.adf)

    combined_adf = pd.concat(group_adfs, ignore_index=True)
    primary_set = calibration_sets[0]

    # create the realization file (with the alternative parameters) and the validation config file
    create_valid_realization_file(
        agent,
        primary_set.eval_params,
        combined_adf,
        general.name,
        LOG,
    )

    # create t-route config file for the validation run
    configfl = os.path.join(
        agent.valid_path, os.path.basename(str(agent.realization_file))
    )
    valid_file = os.path.join(
        agent.valid_path, os.path.basename(configfl).replace("calib", general.name)
    )
    if not os.path.exists(valid_file):
        raise FileNotFoundError("File does not exist: " + str(valid_file))
    with open(valid_file) as fp:
        data = json.load(fp)

    troute_config = data["routing"]["t_route_config_file_with_path"]
    troute_config_best = troute_config.replace(general.name, "valid_best")
    if not os.path.exists(troute_config_best):
        raise FileNotFoundError("File does not exist: " + str(troute_config_best))
    shutil.copy(troute_config_best, troute_config)

    # read validation config file
    config_file_valid = os.path.join(
        agent.valid_path,
        os.path.basename(agent.yaml_file).replace("calib", general.name),
    )
    if not os.path.exists(config_file_valid):
        raise FileNotFoundError("File does not exist: " + str(config_file_valid))
    with open(config_file_valid) as file:
        conf_valid = yaml.safe_load(file)
    general_valid = General(**conf_valid["general"])

    # Change directory to workdir
    os.chdir(general_valid.workdir)

    # Initialize agent
    agent_valid = Agent(
        conf_valid["model"],
        general_valid.valid_path,
        general_valid,
        general_valid.log,
        general_valid.restart,
    )

    if "nwmflow" not in model_conf.keys() or model_conf["nwmflow"] is None:
        LOG.info(
            "No NWM retrospective streamflow simulation is available for this location"
        )
        agent_valid.nwmflow_file = ""
    else:
        agent_valid.nwmflow_file = model_conf["nwmflow"]

    if log_path_overwrite is None:
        LOG.info("Validation Iteration bootstrap complete. Switching to validation iteration job log.")

        job_log_dir = Path(agent_valid.job.workdir)
        job_log_file_name = build_validation_log_file_name(
            calibration_run_id=general.calibration_run_id,
            worker_name=agent_valid.run_name,
            run_kind="iter",
            algorithm=agent_valid.algorithm,
            iteration=iteration,
            bootstrap=False,
        )

        ewts.logger.reset_logger(ewts.CAL_MGR_ID)

        LOG = initialize_logger(
            log_path_overwrite=None,
            log_file_name_override=log_file_name_override or job_log_file_name,
            log_level_override=log_level_override,
            enabled_override=enabled_override,
            reset_file=True,
            default_log_dir=job_log_dir,
        )

    # set environment variables for ngencerf backend and ngen ewts log file location
    set_os_env_key(
        OS_ENV_KEY_RESULTS_DIR, str(Path(agent_valid.job.workdir)), override=False
    )

    # setup prefix for ngen ewts log file name
    set_os_env_key(
        OS_ENV_KEY_NGEN_LOG_FILE_PREFIX, f"{agent.run_name}", override=False
    )

    # Execcute validation simulation
    run_valid_ctrl_best(agent_valid)

    LOG.info("Validation Iteration completed")


def cli():
    """Command-line interface entry point for nwm-validation-iteration."""

    parser = argparse.ArgumentParser(
        description="Create validation inputs based on calibration config file"
    )
    parser.add_argument(
        "config_file", type=Path, help="The configuration yaml file for calibration"
    )
    parser.add_argument(
        "worker_id",
        type=str,
        help="Worked ID as identified by the random string created during calibration",
    )
    parser.add_argument("iter_no", type=int, help="Iteration number")

    # OPTIONAL flags
    parser.add_argument(
        "--log_path_overwrite",
        required=False,
        type=str,
        help="""
        If provided, this file path will be used for logging. If a filename, the file will be overwritten.
        If not provided, a log file path will be decided by the program."""
    )
    parser.add_argument(
        "--logging_enabled",
        required=False,
        type=str_to_bool,
        help="""
        Enable or disable cal-mgr logging.
        Accepts: true/false, yes/no, on/off, 1/0."""
    )
    parser.add_argument(
        "--log_file_name",
        required=False,
        type=str,
        help="""
        If provided, this file name will be used for cal-mgr logging, otherwise it will be decided by the program."""
    )
    parser.add_argument(
        "--log_level",
        required=False,
        type=str,
        help="""
        If provided, this log level will be used for cal-mgr logging. (default=INFO)."""
    )

    args = parser.parse_args()

    with open(args.config_file) as file:
        conf = yaml.safe_load(file)

    general_conf = conf["general"]

    workdir = Path(general_conf["workdir"])
    algorithm = general_conf["strategy"]["algorithm"]
    default_log_dir = workdir / "logs"
    calibration_run_id = general_conf.get("calibration_run_id")

    global LOG
    if args.log_path_overwrite is not None:
        job_log_file_name = build_validation_log_file_name(
            calibration_run_id=calibration_run_id,
            worker_name=args.worker_id,
            run_kind="iter",
            algorithm=algorithm,
            iteration=args.iter_no,
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
        bootstrap_log_file_name = build_validation_log_file_name(
            calibration_run_id=calibration_run_id,
            worker_name=args.worker_id,
            run_kind="iter",
            algorithm=algorithm,
            iteration=args.iter_no,
            bootstrap=True,
        )
        print(f"validation_iteration {args.iter_no} boostrap_log_file_name={bootstrap_log_file_name}", flush=True)

        LOG = initialize_logger(
            log_path_overwrite=None,
            log_file_name_override=args.log_file_name or bootstrap_log_file_name,
            log_level_override=args.log_level,
            enabled_override=args.logging_enabled,
            reset_file=True,
            default_log_dir=default_log_dir,
        )

        LOG.info("Validation Iteration bootstrapping started")

    general = General(**conf["general"])
    general.name = "valid_" + args.worker_id + "_iter" + str(args.iter_no)

    main(
        general,
        conf["model"],
        args.worker_id,
        args.iter_no,
        log_path_overwrite=args.log_path_overwrite,
        log_level_override=args.log_level,
        log_file_name_override=args.log_file_name,
        enabled_override=args.logging_enabled,
    )


if __name__ == "__main__":
    cli()
