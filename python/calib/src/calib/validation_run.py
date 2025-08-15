import logging
import os
import shutil
from typing import TYPE_CHECKING

import pandas as pd

logger = logging.getLogger(__name__)

from .plot_output import plot_valid_output
from .search import _calc_metrics, _execute
from .utils import complete_msg, pushd

if TYPE_CHECKING:
    pass


import logging

from .configuration import NoCalibModel

logger = logging.getLogger(__name__)


def run_valid_ctrl_best(agent):
    """
    Run validation for control and best runs, or execute single-run validation for NoCalibModel.

    Parameters
    ----------
    agent : Agent
        Agent object containing model and configuration info.
    """
    # Single-execution model (NoCalibModel) validation

    if isinstance(agent.model, NoCalibModel):
        logger.info(
            f"Running validation for NoCalibModel (Single Exec): {agent.run_name}"
        )
        # Execute model run and post-process results
        with pushd(agent.job.workdir):
            logger.info(agent.cmd)
            _execute(agent)
            agent.model.postprocess_single_validation_output(agent)
        logger.info("[NoCalibModel] Validation complete.")
        return

    # -----------------------------------------
    # Regular calibrated model validation
    # -----------------------------------------

    shutil.copy(
        agent.realization_file,
        os.path.join(agent.job.workdir, os.path.basename(agent.realization_file)),
    )

    # read nwm retrospective streamflow if exists
    if agent.run_name != "valid_control":
        if agent.nwmflow_file != "":
            if os.path.exists(agent.nwmflow_file):
                logger.info(
                    f"Read NWM retrospective streamflow simulation from: {agent.nwmflow_file}"
                )
                nwm = pd.read_csv(agent.nwmflow_file)
                nwm.columns = ["value_date", "sim_flow"]
                nwm["value_date"] = pd.DatetimeIndex(nwm["value_date"])
                agent.nwmflow = nwm.set_index("value_date")
            else:
                logger.error(f"File does not exist: {agent.nwmflow_file}")
        else:
            agent.nwmflow = None

    # Calculate metrics
    for calibration_object in agent.model.adjustables:
        with pushd(agent.job.workdir):
            logger.info(f"Running simulation for {agent.run_name}")
            _execute(agent)
            time_period = {
                "calib": calibration_object.evaluation_range,
                "valid": calibration_object.valid_evaluation_range,
                "full": calibration_object.full_evaluation_range,
            }

            outputs = [calibration_object.output]
            runs = [agent.run_name]
            if agent.run_name != "valid_control":
                if agent.nwmflow is not None:
                    outputs.append(agent.nwmflow)
                    runs.append("nwm_retro")

            for out1, run1 in zip(outputs, runs):
                metrics = pd.DataFrame()
                logger.info(f"Computing metrics for out1 : {out1}, run1: {run1}")
                for key, value in time_period.items():
                    result = _calc_metrics(
                        out1,
                        calibration_object.observed,
                        value,
                        calibration_object.threshold,
                    )
                    tmp = {**{"run": run1, "period": key}, **result}
                    metrics = pd.concat(
                        [metrics, pd.DataFrame([tmp])], ignore_index=True
                    )
                    metric_out_file = os.path.join(
                        agent.workdir,
                        "{}".format(calibration_object.basinID)
                        + "_metrics_{}.csv".format(run1),
                    )
                    metrics.to_csv(metric_out_file, index=False)

            # Save and move output
            calibration_object.save_valid_output(
                calibration_object.basinID,
                agent.run_name,
                agent.valid_path,
                agent.job.workdir,
                agent.valid_path_output,
            )

            # plot the validation plots (for valid_best or validation with alternative parameters)
            if agent.run_name != "valid_control":
                runs = ["valid_control", "valid_best"]
                if agent.nwmflow is not None:
                    runs.append("nwm_retro")
                if agent.run_name != "valid_best":
                    runs.append(agent.run_name)
                logger.info(f"Generating plots comparing {runs}")

                plot_valid_output(calibration_object, agent, runs, time_period)

            # Indicate completion
            calibration_object.write_run_complete_file(agent.run_name, agent.workdir)
            complete_msg(
                calibration_object.basinID,
                agent.run_name,
                agent.workdir,
                calibration_object.user,
            )
