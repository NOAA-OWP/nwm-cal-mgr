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
    Run validation for control and best run OR for NoCalibModel (single-run).

    Parameters
    ----------
    agent : Agent
        Agent object containing model and configuration info.
    """
    if isinstance(agent.model, NoCalibModel):
        logger.info("Running validation for NoCalibModel (Single Exec)")

        # Ensure directory structure exists
        output_dir = Path(agent.job.workdir) / "Output_Iteration"
        output_dir.mkdir(parents=True, exist_ok=True)

        with pushd(agent.job.workdir):
            agent.model.execute_model()

            # Calculate metrics
            metrics = _calc_metrics(agent.model.output, agent.model.observed,
                                    agent.model.evaluation_range, agent.model.threshold)
            agent.model.metrics = metrics
            df_metrics = pd.DataFrame([metrics])

            # Save output and metrics
            basin = agent.model.basinID
            output_csv = output_dir / f"{basin}_output_single_valid.csv"
            metrics_csv = output_dir / f"{basin}_metrics_single_valid.csv"
            agent.model.output.to_csv(output_csv)
            df_metrics.to_csv(metrics_csv, index=False)
            logger.info(f"Saved output to {output_csv}")
            logger.info(f"Saved metrics to {metrics_csv}")

            # Plotting
            plot_dir = Path(agent.job.workdir) / "Plot_Iteration"
            plot_dir.mkdir(parents=True, exist_ok=True)

            from .plot_functions import (
                plot_streamflow,
                fdc_plot,
                scatterplot_streamflow,
                barplot_metric
            )

            df_merged = agent.model.output.copy()
            df_merged["obs_flow"] = agent.model.observed["obs_flow"]

            # Required plots
            logger.info("---Plotting Hydrograph---")
            plot_streamflow(df_merged, plot_dir / f"{basin}_hydrograph_valid.png", basin, suffix="valid")

            logger.info("---Plotting FDC---")
            fdc_plot(df_merged, plot_dir / f"{basin}_fdc_valid.png", basin, suffix="valid")

            logger.info("---Plotting Scatterplot---")
            scatterplot_streamflow(df_merged, plot_dir / f"{basin}_scatterplot_valid.png", basin, suffix="valid")

            # Optional barplot (if compatible with structure)
            try:
                logger.info("---Plotting Barplot of Metrics---")
                df_metrics["runtype"] = "valid"
                barplot_metric(df_metrics, plot_dir / f"{basin}_barplot_metrics_valid.png", title="Validation Metrics")
            except Exception as e:
                logger.warning(f"Could not create barplot: {e}")

        logger.info("[NoCalibModel] Validation complete.")
        return

    # -----------------------------------------
    # Regular validation logic (unchanged)
    # -----------------------------------------
    logger.info("Running validation for regular calibrated model.")

    model = agent.model
    basin = model.basinID
    realization_file = model.realization_file
    observed = model.observed
    threshold = model.threshold
    valid_path = agent.valid_path

    with pushd(agent.job.workdir):
        for run_type in ['valid_control', 'valid_best']:
            model.use_realization_file(run_type)

            agent.execute_model()

            # Load output
            result = _calc_metrics(model.output, observed, model.evaluation_range, threshold)
            df_metrics = pd.DataFrame([result])
            run_path = Path(valid_path) / f"{basin}_metrics_{run_type}.csv"
            df_metrics.to_csv(run_path, index=False)
            logger.info(f"Saved metrics: {run_path}")

            output_path = Path(valid_path) / f"{basin}_output_{run_type}.csv"
            model.output.to_csv(output_path)
            logger.info(f"Saved output: {output_path}")

    # Plotting (unchanged)
    plot_valid_output(agent, basin, valid_path)

