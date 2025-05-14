import os
import logging
import pandas as pd
from pathlib import Path
from .search import _calc_metrics
from .plot_output import plot_valid_output
from .utils import pushd
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
        logger.info("Running validation for NoCalibModel (Single Exec)")
        # Execute model run and post-process results
        with pushd(agent.job.workdir):
            agent.model.execute_model()
            agent.model.postprocess_single_validation_output(agent)
        logger.info("[NoCalibModel] Validation complete.")
        return

    # -----------------------------------------
    # Regular calibrated model validation
    # -----------------------------------------
    logger.info("Running validation for regular calibrated model.")
    model = agent.model
    basin = model.basinID
    observed = model.observed
    threshold = model.threshold
    valid_path = agent.valid_path

    # Execute control and best validation runs
    with pushd(agent.job.workdir):
        for run_type in ['valid_control', 'valid_best']:
            model.use_realization_file(run_type)
            agent.execute_model()

            # Calculate metrics for this run
            result = _calc_metrics(model.output, observed, model.evaluation_range, threshold)
            df_metrics = pd.DataFrame([result])
            metrics_file = Path(valid_path) / f"{basin}_metrics_{run_type}.csv"
            df_metrics.to_csv(metrics_file, index=False)
            logger.info(f"Saved metrics: {metrics_file}")

            # Save simulation output for this run
            output_file = Path(valid_path) / f"{basin}_output_{run_type}.csv"
            model.output.to_csv(output_file)
            logger.info(f"Saved output: {output_file}")

    # Generate validation comparison plots for control vs. best
    runs = ['valid_control', 'valid_best']
    plot_valid_output(model, agent, runs, model.eval_params.time_period)
    logger.info("Validation plots generated for control and best runs.")

