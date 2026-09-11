from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
import inspect
import argparse
import re

import ewts

def str_to_bool(value: str) -> bool:
    value = value.lower()
    if value in {"true", "t", "yes", "y", "1", "on", "enabled", "enable"}:
        return True
    if value in {"false", "f", "no", "n", "0", "off", "disabled", "disable"}:
        return False
    raise argparse.ArgumentTypeError(
        f"Invalid boolean value: '{value}'"
    )


def create_timestamp(
    fmt: Literal["default", "compact"] = "default"
) -> str:
    now = datetime.now(timezone.utc)

    if fmt == "compact":
        return now.strftime("%Y%m%dT%H%M%S")

    return now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]


def build_calibration_log_file_name(
    *,
    calibration_run_id: int | None,
    bootstrap: bool = False
) -> str:
    job_id = calibration_run_id
    if calibration_run_id:
        base =  f"cal_mgr_job_{calibration_run_id}_calib"
    else:
        base  =  f"cal_mgr_{create_timestamp('compact')}_calib"

    if bootstrap:
        return f"{base}_bootstrap.log"
    
    return f"{base}.log"

def build_validation_log_file_name(
    *,
    calibration_run_id: int | None,
    worker_name: str | None = None,
    run_kind: str,
    algorithm: str,
    iteration: int | None = None,
    bootstrap: bool = False
) -> str:
    """
    run_kind:
      - valid_control
      - valid_best
      - iter
    """
    if calibration_run_id:
        prefix = f"cal_mgr_job_{calibration_run_id}"
    else:
        prefix = f"cal_mgr_{create_timestamp('compact')}"

    if run_kind not in {"valid_control", "valid_best", "iter"}:
        raise ValueError(f"Unsupported run_kind: {run_kind}")
    elif run_kind == "iter": 
        run_kind_suffix = f"_{worker_name}" if not bootstrap else f"_valid_{worker_name}_iter{iteration}"
    else:   
        run_kind_suffix = f"_{run_kind}"

    if bootstrap:
        return f"{prefix}{run_kind_suffix}_bootstrap.log"
    
    return f"{prefix}{run_kind_suffix}.log"


def resolve_log_target(
    *,
    log_path_overwrite: str | None = None,
    log_file_name_override: str | None = None,
    default_log_dir: str | Path | None = None,
) -> tuple[Path, str]:
    resolved_log_dir: Path | None = None
    resolved_log_file_name: str | None = None

    if log_path_overwrite:
        log_path = Path(log_path_overwrite)
        print(f"log_path_overwrite = {log_path!s}")

        if log_path.exists():
            if log_path.is_dir():
                resolved_log_dir = log_path
                resolved_log_file_name = log_file_name_override or "cal_mgr.log"
            else:
                resolved_log_dir = log_path.parent
                resolved_log_file_name = log_path.name
        else:
            if str(log_path_overwrite).endswith(("/", "\\")):
                resolved_log_dir = log_path
                resolved_log_file_name = log_file_name_override or "cal_mgr.log"
            elif log_path.suffix:
                resolved_log_dir = log_path.parent
                resolved_log_file_name = log_path.name
            else:
                resolved_log_dir = log_path
                resolved_log_file_name = log_file_name_override or "cal_mgr.log"
    else:
        if default_log_dir is not None:
            resolved_log_dir = Path(default_log_dir)
        elif Path("/ngencerf/data").exists():
            resolved_log_dir = Path("/ngencerf/data/run-logs/cal_mgr")
        else:
            resolved_log_dir = Path.home() / "run-logs" / "cal_mgr"

        resolved_log_file_name = (
            log_file_name_override or f"cal_mgr_{create_timestamp('compact')}.log"
        )

    return resolved_log_dir, resolved_log_file_name


def initialize_logger(
    *,
    log_path_overwrite: str | None = None,
    log_level_override: str | None = None,
    log_file_name_override: str | None = None,
    enabled_override: bool | None = None,
    reset_file: bool = False,
    default_log_dir: str | Path | None = None,
) -> ewts.logger.EwtsLogger:
    log_level = log_level_override if log_level_override is not None else "INFO"

    resolved_log_dir, resolved_log_file_name = resolve_log_target(
        log_path_overwrite=log_path_overwrite,
        log_file_name_override=log_file_name_override,
        default_log_dir=default_log_dir,
    )

    resolved_log_dir.mkdir(parents=True, exist_ok=True)
    full_log_path = resolved_log_dir / resolved_log_file_name

    if reset_file or log_path_overwrite:
        print(
            f"log setup: Deleting file, if already exists, to start a new log file: {full_log_path!s}, "
        )
        try:
            full_log_path.unlink()
        except FileNotFoundError:
            pass

    print(f"CALMGR EWTS Logging into: {full_log_path}")

    return ewts.logger.setup_logger(
        ewts.CAL_MGR_ID,
        level=log_level,
        log_dir=resolved_log_dir,
        log_file_name=resolved_log_file_name,
        running_in_ngen=False,
        enabled=enabled_override,
    )

def get_calmgr_logger() -> ewts.logger.EwtsLogger:
    return ewts.logger.get_logger(ewts.CAL_MGR_ID)
