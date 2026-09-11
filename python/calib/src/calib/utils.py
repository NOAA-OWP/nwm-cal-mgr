"""
This module contains utility functions for executing calibration and validation run.

@author: Nels Frazer, Xia Feng
"""

import smtplib
from contextlib import contextmanager
from email.mime.text import MIMEText
import ewts
from os import PathLike, chdir, getcwd, path, environ
from typing import Union

from .ngencerf import report

OS_ENV_KEY_RESULTS_DIR = "NGEN_RESULTS_DIR"
OS_ENV_KEY_NGEN_LOG_FILE_PREFIX = "NGEN_LOG_FILE_PREFIX"

from common import get_calmgr_logger

def _logger():
    return get_calmgr_logger()

@contextmanager
def pushd(path: Union[str, PathLike]) -> None:
    """Change current working directory to the given path.

    Parameters
    ----------
    path : New directory path

    Returns
    ----------
    None

    """
    # Save current working directory
    cwd = getcwd()

    # Change the directory
    chdir(path)
    try:
        yield
    finally:
        chdir(cwd)


def complete_msg(
    basinid: str,
    run_name: str,
    path: Union[str, PathLike] = None,
    user_email: str = None,
) -> None:
    """Send email notification to user if run is completed.

    Parameters
    ----------
    basinid : Basin ID
    run_name : Calibration or validation run
    path : Work directory
    user_email : User email address

    Returns
    ----------
    None

    """
    subject = run_name.capitalize() + " Run for {}".format(basinid) + " Is Completed"
    content = subject + " at " + path if path else subject
    if user_email:
        msg = MIMEText(content)
        msg["Subject"] = subject
        msg["From"] = "foo@example.com"
        msg["To"] = user_email
        try:
            server = smtplib.SMTP("foo-server-name")
            server.sendmail(msg["From"], user_email, msg.as_string())
        except Exception as e:
            print(e)
            print("completion email " + "for {}".format(basinid) + "can't be sent")
        finally:
            server.quit()
    else:
        print(content)


def report_to_ngencerf(agent, iteration=0, first_iter=True):
    if agent._general.ngen_cerf:
        print(
            f"Reporting iteration {iteration} to ngen-cerf with run_id : {agent._general.calibration_run_id}"
        )
        worker = (
            path.basename(agent.job.workdir).replace("ngen_", "").replace("_worker", "")
        )
        report(
            agent._general.calibration_run_id,
            iteration,
            worker,
            first_iter,
            agent._general.auth_token,
            agent._general.ngencerf_base_url
        )


def set_os_env_key(key: str, val: str, override: bool = True) -> None:
    """Set the value of the OS environment key.
    Optionally, keep the existing value for that key without overriding, if it already exists.

    Parameters:
        key : str
            OS environment key whose value will be modified.
        val : str
            New value to set to.
        override : bool (default True)
            If True, then do replace the existing value of that key if it already exists.
            If False, then do not replace the value.
    """
    errors: list[Exception] = []
    if not isinstance(key, str):
        errors.append(TypeError(f"For key {key}, expected type {str}, got {type(key)}"))
    if not isinstance(val, str):
        errors.append(
            TypeError(f"For value {val}, expected type {str}, got {type(val)}")
        )
    if errors:
        raise RuntimeError(errors)

    if key in environ:
        msg_suffix = f"OS env key {repr(key)} already exists with value {repr(environ[key])}, override={override}"
        if not override:
            _logger().info("Will not override: " + msg_suffix)
            return
        _logger().info("Will override: " + msg_suffix)

    _logger().info(f"Setting OS env key {repr(key)} to value {repr(val)}.")
    environ[key] = val
