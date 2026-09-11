"""
This module creates interface to adjust parameters, store
observation, and save streamflow from calibration and validation
runs and perform evaluation for a set of calibration catchments.

@author: Nels Frazer, Xia Feng
"""

import glob
import os
import shutil
import tempfile
import time

from pathlib import Path
from typing import TYPE_CHECKING, Optional, Sequence

import netCDF4
import pandas as pd
from hypy.nexus import Nexus
from pandas import DataFrame  # type: ignore
from pandas.api.types import is_numeric_dtype, is_object_dtype, is_string_dtype

from .calibratable import Adjustable, Evaluatable

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path
    from typing import Tuple

    from pandas import DataFrame

    from .model import EvaluationOptions

from common import get_calmgr_logger
logger = get_calmgr_logger()

class CalibrationSet(Evaluatable):
    """A HY_Features based catchment with additional calibration information/functionality."""

    def __init__(
        self,
        adjustables: Sequence[Adjustable],
        eval_nexus: Nexus,
        routing_output: "Path",
        start_time: str,
        end_time: str,
        eval_params: "EvaluationOptions",
        obsflow_file: Optional[Path],
        nwmflow_file: Optional[Path],
        wb_lst: list,
    ) -> None:
        
        """Construct attributes for the CalibrationSet object.

        Parameters
        ----------
        adjustables: Adjustable object
        eval_nexus : Obesrvable nexus ID
        routing_output : Routing output file
        start_time : Starting simulation time
        end_time : Endig simulation time
        eval_params : EvaluationOptions object
        obsflow_file : Streamflow observation file
        nwmflow_file: nwm retrospective streamflow simulation

        """
        super().__init__(eval_params)
        self._eval_nexus = eval_nexus
        self._adjustables = adjustables
        self._output_file = routing_output

        # Read observation data if observation file is provided
        if obsflow_file is not None:
            if os.path.exists(obsflow_file):
                logger.info(f"Read observed streamflow from: {obsflow_file}")
                obs = pd.read_csv(obsflow_file)

                # if obs is empty, raise an error
                if obs.empty:
                    msg = f"Streamflow observation file is empty: {obsflow_file}"
                    logger.error(msg)
                    raise ValueError(msg)
                
                cols = obs.columns.str.lower()
                obs.columns = cols

                # function to detect time column
                def detect_time_column(df: pd.DataFrame, time_col: str = "time"):
                    for col in df.columns:
                        if is_object_dtype(df[col]) or is_string_dtype(df[col]):
                            parsed = pd.to_datetime(df[col], errors="coerce")
                            if parsed.notna().all():
                                if col.lower() != time_col:
                                    logger.info(
                                        f"Using '{col}' as 'time' column for streamflow observation file"
                                    )
                                return col

                    msg = "No column in streamflow observation file contains fully valid datetimes"
                    logger.error(msg)
                    raise ValueError(msg)

                # function to detect flow column
                def detect_flow_column(df: pd.DataFrame, flow_col: str = "obs_flow"):
                    for col in df.columns:
                        if is_numeric_dtype(df[col]):
                            if col.lower() != flow_col:
                                logger.info(
                                    f"Using '{col}' as 'obs_flow' column for streamflow observation file"
                                )
                            return col

                    msg = "No column in streamflow observation file contains numeric flow values"
                    logger.error(msg)
                    raise ValueError(msg)

                # if 'time' column not present, try to detect it
                time_col = "time" if "time" in obs.columns else detect_time_column(obs)

                # Normalize to canonical name "value_date" (i.e., datetime of observation value) used elsewhere
                obs = obs.rename(columns={time_col: "value_date"})

                # if 'obs_flow' column not present, try to detect it
                flow_col = (
                    "obs_flow" if "obs_flow" in obs.columns else detect_flow_column(obs)
                )
                obs = obs.rename(columns={flow_col: "obs_flow"})

                obs["value_date"] = pd.to_datetime(obs["value_date"], errors="raise")
                self._observed = obs.set_index("value_date")
            else:
                logger.error(
                    f"Filepath for observed streamflow is not valid: {obsflow_file}"
                )
        else:
            # Otherwise pull observation from NWIS portal on-the-fly
            logger.info("Retrieving observed streamflow data from NWIS ...")
            obs = self._eval_nexus._hydro_location.get_data(start_time, end_time)
            self._observed = (
                obs.set_index("value_time")["value"].resample("1H").nearest()
            )
            self._observed.rename("obs_flow", inplace=True)
            self._observed = (
                self._observed * 0.028316847
            )  # Convert observation from ft^3/s to m^3/s

        self._output = None
        self._eval_range = self.eval_params._eval_range
        self._valid_eval_range = self.eval_params._valid_eval_range
        self._full_eval_range = self.eval_params._full_eval_range
        self._wb_lst = wb_lst

    @property
    def evaluation_range(self) -> "Tuple[datetime, datetime]":
        return self._eval_range

    @property
    def valid_evaluation_range(self) -> "Tuple[datetime, datetime]":
        return self._valid_eval_range

    @property
    def full_evaluation_range(self) -> "Tuple[datetime, datetime]":
        return self._full_eval_range

    @property
    def adjustables(self):
        return self._adjustables

    @property
    def output(self) -> "DataFrame":
        """The model output hydrograph for this catchment.

        Reads the output file safely, making a temporary copy to avoid parallel HDF5 issues.
        Returns None if the file does not exist.
        """
        if not Path(self._output_file).exists():
            logger.info("Output file does not exist.")
            return None

        max_attempts = 5  # Retries up to max_attempts in case of transient HDF5 errors.
        delay = 0.5  # seconds
        hydrograph = None

        for attempt in range(max_attempts):
            try:
                # Copy to temporary file before reading, avoiding simultaneous access conflicts.
                with tempfile.NamedTemporaryFile(suffix=".nc") as tmp_file:
                    shutil.copy(self._output_file, tmp_file.name)
                    ncvar = netCDF4.Dataset(tmp_file.name, "r")

                    # Extract the flow at the evaluation nexus
                    fid_index = [
                        list(ncvar["feature_id"][0:]).index(int(fid))
                        for fid in self._wb_lst
                    ]
                    self._output = pd.DataFrame(
                        data={
                            "sim_flow": pd.DataFrame(
                                ncvar["flow"][fid_index], index=fid_index
                            ).T.sum(axis=1)
                        }
                    )

                    # Get date from troute NetCDF file
                    times = netCDF4.num2date(
                        ncvar["time"][:],
                        units=ncvar["time"].units,
                    )
                    dt_range = pd.DatetimeIndex([pd.Timestamp(t.isoformat()) for t in times])
                    self._output.index = dt_range
                    self._output.index.name = "Time"
                    self._output = self._output.resample("1h").first()

                    logger.debug("Simulation results ready (DataFrame populated)")
                    hydrograph = self._output

                break  # success, exit retry loop

            except OSError as e:
                # Handle transient HDF5 errors
                logger.warning(f"Attempt {attempt + 1} failed to read NetCDF file: {e}")
                time.sleep(delay)
            except Exception as e:
                raise e

        if hydrograph is None or hydrograph.empty:
            msg = "Simulated hydrograph is unavailable or empty."
            logger.error(msg)
            raise ValueError(msg)

        return hydrograph

    @output.setter
    def output(self, df):
        self._output = df

    @property
    def observed(self) -> "DataFrame":
        """Observed hydrograph for this catchment."""
        hydrograph = self._observed
        if hydrograph is None:
            raise (RuntimeError("Error reading observation for {}".format(self._id)))
        return hydrograph

    @property
    def nwmflow(self) -> "DataFrame":
        """NWM retrospective hydrograph fromfor this catchment."""
        hydrograph = None
        if hasattr(self, "_nwmflow"):
            hydrograph = self._nwmflow
        # if hydrograph is None:
        #    raise(RuntimeError("Error reading NWM retrospective streamflow for {}".format(self._id)))
        return hydrograph

    @observed.setter
    def observed(self, df):
        self._observed = df

    def save_calib_output(
        self,
        i,
        output_iter_file: "Path",
        last_output_file: "Path",
        calib_path1: "Path",
        calib_path2: "Path",
        calib_path3: Path = None,
        save_output_iter_flag=False,
    ) -> None:
        """Save model output from calibration run.

        Parameters:
        ----------
        i : iteration
        output_iter_file : output file at each iteration
        last_output_file : last output file
        calib_path1 : directory to store streamflow file at each iteration
        calib_path2 : current agent job directory
        calib_path3 : directory to store catchment and nexsus output plus other output files, default None
        save_output_iter_flag : whether to save output at each iteration

        """
        if os.path.exists(self._output_file):
            flow_output = self._output.reset_index()
            flow_output = flow_output.rename(columns={"index": "Time"})
            if i == 0 or save_output_iter_flag:
                filename_iter = os.path.join(
                    calib_path1, output_iter_file + str("{:04d}").format(i) + ".csv"
                )
                flow_output.to_csv(filename_iter, index=False)
            flow_output.to_csv(last_output_file, index=False)

            shutil.move(
                self._output_file,
                os.path.join(
                    os.path.dirname(last_output_file),
                    "{}_last".format(self._output_file),
                ),
            )
        if calib_path3 is None:
            calib_path3 = calib_path2
        for pat in ["nex*.csv", "cat*.csv", "cat*.nc"]:
            for f in glob.glob(os.path.join(calib_path2, pat)):
                shutil.move(f, calib_path3 + "/" + os.path.basename(f))
        if len(glob.glob(os.path.join(calib_path2, "*.out"))) > 0:
            for outfl in glob.glob(os.path.join(calib_path2, "*.out")):
                shutil.move(outfl, calib_path3 + "/" + os.path.basename(outfl))

    def save_valid_output(
        self,
        basinid: str,
        run_name: str,
        valid_path1: "Path",
        valid_path2: "Path",
        valid_path3: "Path",
    ) -> None:
        """Save model output from validation run.

        Parameters:
        ----------
        run_name : Control or best run
        valid_path1 : Validation run main directory
        valid_path2 : Validation run job work directory
        valid_path3 : Subdrirectory under valid_path2 to store output files

        """
        if os.path.exists(self._output_file):
            flow_output = self._output.reset_index()
            flow_output = flow_output.rename(columns={"index": "Time"})
            filename_valid = os.path.join(
                valid_path1, basinid + "_output_" + run_name + ".csv"
            )
            flow_output.to_csv(filename_valid, index=False)
            shutil.move(
                self._output_file,
                os.path.join(valid_path2, "{}_".format(self._output_file) + run_name),
            )
        for pat, ext in [("nex*.csv", ".csv"), ("cat*.csv", ".csv"), ("cat*.nc", ".nc")]:
            for f in glob.glob(os.path.join(valid_path2, pat)):
                shutil.move(
                    f,
                    valid_path3
                    + "/"
                    + os.path.basename(f).split(".")[0]
                    + "_{}".format(run_name)
                    + ext,
                )
        if len(glob.glob(os.path.join(valid_path2, "*.out"))) > 0:
            for outfl in glob.glob(os.path.join(valid_path2, "*.out")):
                shutil.move(
                    outfl,
                    valid_path3
                    + "/"
                    + os.path.basename(outfl).split(".")[0]
                    + "_{}".format(run_name)
                    + ".out",
                )

    def save_best_output(self, best_output_file: "Path", best_save_flag=False) -> None:
        """Save the output at the best iteration

        Parameters:
        ----------
        best_output_file : Best output file name
        best_save_flag : Whether save output as best output

        """
        if self._output is not None and best_save_flag:
            flow_output = self._output.reset_index()
            flow_output = flow_output.rename(columns={"index": "Time"})
            flow_output.to_csv(best_output_file, index=False)

    def save_output(self, i) -> None:
        """Save the last output to output for iteration i."""
        if os.path.exists(self._output_file):
            shutil.move(self._output_file, "{}_last".format(self._output_file))

    def check_point(self, path: "Path") -> None:
        """Save calibration information."""
        for adjustable in self.adjustables:
            adjustable.df.to_parquet(path / adjustable.check_point_file)

    def restart(self) -> int:
        try:
            for adjustable in self.adjustables:
                adjustable.restart()
        except FileNotFoundError:
            return 0
        return super().restart()


class UniformCalibrationSet(CalibrationSet, Adjustable):
    """A HY_Features based catchment with additional calibration information/functionality"""

    def __init__(
        self,
        eval_nexus: Nexus,
        routing_output: "Path",
        start_time: str,
        end_time: str,
        eval_params: "EvaluationOptions",
        obsflow_file: Optional["Path"],
        nwmflow_file: Optional["Path"],
        wb_lst: list,
        params: dict = {},
    ) -> None:
        """Constructor for the UniformCalibrationSet object."""
        super().__init__(
            adjustables=[self],
            eval_nexus=eval_nexus,
            routing_output=routing_output,
            start_time=start_time,
            end_time=end_time,
            eval_params=eval_params,
            obsflow_file=obsflow_file,
            nwmflow_file=nwmflow_file,
            wb_lst=wb_lst,
        )
        Adjustable.__init__(
            self=self, df=DataFrame(params).rename(columns={"init": "0"})
        )

        # For now, set this to None so meta update does the right thing
        # at some point, may want to refactor model update to handle this better
        self._id = None

    # Required Adjustable properties
    @property
    def id(self) -> str:
        """An identifier for this unit, used to save unique checkpoint information."""
        return self._id

    def save_output(self, i) -> None:
        """
        Save the last output to output for iteration i
        """
        # FIXME ensure _output_file exists
        # FIXME re-enable this once more complete
        shutil.move(self._output_file, "{}_last".format(self._output_file))

    # Update handled in meta, TODO remove this method???
    def update_params(self, iteration: int) -> None:
        pass

    # Override this file name
    @property
    def check_point_file(self) -> "Path":
        return Path("parameter_df_state_{}.parquet".format(self._eval_nexus.id))

    def restart(self):
        """Prepare for calibration restart run."""
        # Reload the evaluation information
        start_iteration = Evaluatable.restart(self)
        try:
            # Reload the param space for the adjustable
            Adjustable.restart(self)
            shutil.copy(
                str(self.check_point_file),
                str(self.check_point_file)
                + "_before_restart_"
                + time.strftime("%Y%m%d_%H%M%S"),
            )
            try:
                self.df.pop(str(start_iteration))
                self.check_point("./")
            except KeyError:
                pass
        except FileNotFoundError:
            return 0

        return start_iteration
