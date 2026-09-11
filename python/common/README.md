# common

Shared utilities for `nwm-cal-mgr` Python components.

This package provides reusable functionality used across calibration, configuration, and supporting modules. Its primary purpose is to centralize common logic (such as logging setup) to ensure consistency and reduce duplication.

---

## Features

- Centralized EWTS logger initialization
- Safe fallback logger binding (`ensure_logger_initialized`)
- Timestamp utilities
- Designed for reuse across multiple modules

---

## Installation

This package is installed as part of the `nwm-cal-mgr` Docker build:

```bash
cd python/common
pip install .
```

---

## Usage

### Initialize logger (preferred in entry points)

```python
from common import initialize_logger

logger = initialize_logger()
logger.info("Logger initialized")
```

---

## Logger Configuration Options

The `initialize_logger()` function allows customization of logging behavior to support different environments and workflows.

### Available options

```python
initialize_logger(
    log_path_overwrite: str | None = None,
    log_level_override: str | None = None,
    log_file_name_override: str | None = None,
    enabled_override: bool | None = None,
)
```

### Parameter details

* **`log_path_overwrite`**

  * Full path to a log file **or** directory
  * Examples:

    * `/tmp/my_log.log` → writes to specific file
    * `/tmp/logs/` → writes to directory with default filename
  * If the file already exists, it will be overwritten

* **`log_file_name_override`**

  * Custom log file name when using a directory
  * Example:

    ```python
    log_file_name_override="custom.log"
    ```

* **`log_level_override`**

  * Override default log level (e.g., `"DEBUG"`, `"INFO"`, `"WARNING"`)
  * Example:

    ```python
    log_level_override="DEBUG"
    ```

* **`enabled_override`**

  * Enable or disable logging entirely
  * Example:

    ```python
    enabled_override=False
    ```

---

### Examples

#### Custom log directory

```python
from common import initialize_logger

logger = initialize_logger(
    log_path_overwrite="/tmp/my-logs/"
)
```

---

#### Custom file and debug logging

```python
logger = initialize_logger(
    log_path_overwrite="/tmp/my-logs/",
    log_file_name_override="debug.log",
    log_level_override="DEBUG"
)
```

---

#### Disable logging

```python
logger = initialize_logger(enabled_override=False)
```

---

### Default behavior

If no overrides are provided, logs are written to:

```
~/run-logs/cal_mgr/
```

with a timestamped filename such as:

```
cal_mgr_20260402T153045.log
```

### Ensure logger is initialized (safe fallback)

Use this in modules that may be executed independently:

```python
from common import ensure_logger_initialized
import ewts

logger = ensure_logger_initialized()
logger.info("Logging safely")
```

This will:
- use an existing logger if already initialized
- otherwise initialize a default logger and emit a warning

---

## Timestamp utility

```python
from common import create_timestamp

ts = create_timestamp("compact")  # e.g., 20260402T153045
```

---

## Design Principles

- No logging side effects at import time
- Explicit initialization at entry points
- Safe fallback for robustness
- Minimal dependencies

---

## Notes

- This package assumes EWTS logging is available and installed in the environment.
- It is not intended to be used as a standalone library outside `nwm-cal-mgr`.

---

## Versioning

This package follows semantic versioning:

- `0.x.x` → early development, subject to change
- `1.0.0` → stable API (future)

---

## Authors

Maintained as part of the NGWPC `nwm-cal-mgr` project.
