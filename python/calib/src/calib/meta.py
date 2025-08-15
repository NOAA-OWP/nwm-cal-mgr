"""
This is a class to hold model job run meta data.

@author: Nels Frazer
"""

import logging
import os
import random
import string
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path


def _create_worker_dir(prefix: str, suffix: str, parent_dir: str) -> str:
    """
    Creates a worker directory with default permissions.

    Args:
        prefix (str): Prefix for the directory name.
        suffix (str): Suffix for the directory name.
        parent_dir (str): Parent directory where the worker directory will be created.

    Returns:
        str: The path to the created worker directory as a string.
    """
    unique_part = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    worker_dir = os.path.join(parent_dir, f"{prefix}{unique_part}{suffix}")
    os.makedirs(worker_dir)  # Uses default permissions based on umask
    return worker_dir


class JobMeta:
    """Structure for holding model job meta data."""

    def __init__(
        self, name: str, parent_workdir: Path, workdir: Path = None, log=False
    ):
        """Create a job meta data structure.

        Parameters:
        name (str): Name of the job used to construct log files
        workdir (Path): Working directory to stage the job under
        log (bool, optional): Whether or not to create a log file for the job. Defaults to False.

        """
        if workdir is None:
            self._workdir = Path(
                _create_worker_dir(
                    prefix=name + "_", suffix="_worker", parent_dir=str(parent_workdir)
                )
            ).resolve()
            logger.info(f"Creating new worker: {self._workdir}")
        else:
            self._workdir = workdir
            logger.info(f"Using existing worker {self._workdir}")

        self._log_file = None
        if log:
            self._log_file = self._workdir / Path(name + "_stdout_stderr.log")

    @property
    def workdir(self) -> "Path":
        return self._workdir

    @workdir.setter
    def workdir(self, path: "Path") -> None:
        self._workdir = path
        if self._log_file is not None:
            self._log_file = self._workdir / Path(self._log_file.name)

    @property
    def log_file(self) -> "Path":
        """
        Path to the job's log file, or None.
        """
        return self._log_file
