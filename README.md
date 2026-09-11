# NWM Calibration Manager
nwm-cal-mgr is a Python repository that provides tools for automatic calibration and validation of [NGen](https://github.com/noaa-owp/ngen) Formulations. Currently, the following three optimization algorithms are supported:
- Dynamic Dimensioned Search (DDS)
- Grey Wolf Optimizer (GWO)
- Particle Swarm Optimizer (PSO)

## Table of Contents

- [Introduction](#introduction)
- [Automated Installation](#automated-installation)
- [Manual Installation](#manual-installation)
- [Verify Installation](#verify-installation)
- [Run Calibration and Validation](#run-calibration-and-validation)
- [Docker Container](#docker-container)
  
## Introduction
Instructions on how to install, configure, and run calibration/validation are given below, where:

* `[WORK_DIR]` refers to the parent directory in which repositories are cloned
* `[VENV_DIR]` refers to the Python virtual environment directory

You can choose from the following installation options:

1. **Automated local installation**
2. **Manual local installation**
3. **Docker container installation** (recommended)

Note for local installations (options 1 and 2), you will also need to install ngen (https://github.com/NGWPC/ngen) and 
its various submodules locally, in order to run calibration and validation workflows. 

---

## Automated installation

The following installer script automates the development installation workflow. It:

1. creates or reuses a Python virtual environment,
2. clones or updates `nwm-cal-mgr`,
3. installs `nwm-cal-mgr` from the local clone, and
4. installs the dependencies directly from GitHub:
   - `mswm` from `nwm-msw-mgr`: model setup workflow manager 
   - `nwm_metrics` from `nwm-eval-mgr`: evaluation metrics
   - `ewts` from `nwm-ewts`: error and warning trapping system

### 1. Save the installer script

Save the following script as `install_nwm_cal_mgr.sh`.

<details>
<summary><strong>Show installer script</strong></summary>

```bash
#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="[install-nwm-cal-mgr]"

usage() {
  cat << EOF
Usage:
  $(basename "$0") [options]

Install nwm-cal-mgr for local development by:
  1) creating/updating a Python virtual environment
  2) cloning/updating nwm-cal-mgr locally
  3) installing nwm-cal-mgr from the local clone
  4) installing dependencies (mswm, nwm_metrics, ewts) directly from GitHub

Options:
  --work-dir <path>        Parent directory for local clone of nwm-cal-mgr
                           default: current directory
  --venv-dir <path>        Virtual environment directory
                           default: ./venv
  --org <github_org>       GitHub organization/user for all repos
                           default: ngwpc

  --ref <git_ref>          Shared git ref for all repos (branch, tag, or SHA)
                           default: development

  --cal-ref <git_ref>      Override ref for nwm-cal-mgr
  --msw-ref <git_ref>      Override ref for nwm-msw-mgr
  --eval-ref <git_ref>     Override ref for nwm-eval-mgr
  --ewts-ref <git_ref>     Override ref for nwm-ewts

  --editable               Install nwm-cal-mgr in editable mode

  --python                 Python executable to use for creating the virtual environment
                           default: python3.12  

  -h, --help               Show this help message
EOF
}

WORK_DIR="$(pwd)"
VENV_DIR="$(pwd)/venv"
ORG="ngwpc"

COMMON_REF=""
CAL_REF=""
MSW_REF=""
EVAL_REF=""
EWTS_REF=""

DEFAULT_REF="development"
EDITABLE=0
PYTHON_BIN="python3.12"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --work-dir)
      WORK_DIR="$2"
      shift 2
      ;;
    --venv-dir)
      VENV_DIR="$2"
      shift 2
      ;;
    --org)
      ORG="$2"
      shift 2
      ;;
    --ref)
      COMMON_REF="$2"
      shift 2
      ;;
    --cal-ref)
      CAL_REF="$2"
      shift 2
      ;;
    --msw-ref)
      MSW_REF="$2"
      shift 2
      ;;
    --eval-ref)
      EVAL_REF="$2"
      shift 2
      ;;
    --ewts-ref)
      EWTS_REF="$2"
      shift 2
      ;;
    --editable)
      EDITABLE=1
      shift
      ;;
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "$LOG_PREFIX ERROR: unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

CAL_REF="${CAL_REF:-${COMMON_REF:-$DEFAULT_REF}}"
MSW_REF="${MSW_REF:-${COMMON_REF:-$DEFAULT_REF}}"
EVAL_REF="${EVAL_REF:-${COMMON_REF:-$DEFAULT_REF}}"
EWTS_REF="${EWTS_REF:-${COMMON_REF:-$DEFAULT_REF}}"

CAL_DIR="${WORK_DIR}/nwm-cal-mgr"

echo "$LOG_PREFIX Work dir       : $WORK_DIR"
echo "$LOG_PREFIX Venv dir       : $VENV_DIR"
echo "$LOG_PREFIX GitHub org     : $ORG"
echo "$LOG_PREFIX nwm-cal-mgr ref: $CAL_REF"
echo "$LOG_PREFIX mswm ref       : $MSW_REF"
echo "$LOG_PREFIX nwm_metrics ref: $EVAL_REF"
echo "$LOG_PREFIX ewts ref       : $EWTS_REF"
echo "$LOG_PREFIX Editable       : $EDITABLE"

mkdir -p "$WORK_DIR"

if [[ ! -d "$VENV_DIR" ]]; then

  if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "$LOG_PREFIX ERROR: Python not found: $PYTHON_BIN"
    exit 1
  fi

  echo "$LOG_PREFIX Creating virtual environment at $VENV_DIR using $PYTHON_BIN"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
else
  echo "$LOG_PREFIX Reusing existing virtual environment at $VENV_DIR"
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip

if [[ -d "$CAL_DIR/.git" ]]; then
  echo "$LOG_PREFIX Updating existing clone: $CAL_DIR"
  cd "$CAL_DIR"

  git remote set-url origin "https://github.com/${ORG}/nwm-cal-mgr.git"
  git fetch --all --tags
  git checkout "$CAL_REF"

  if git ls-remote --exit-code --heads origin "$CAL_REF" >/dev/null 2>&1; then
    git pull --ff-only origin "$CAL_REF"
  else
    echo "$LOG_PREFIX $CAL_REF is not a remote branch; skipping git pull"
  fi
else
  echo "$LOG_PREFIX Cloning nwm-cal-mgr into $CAL_DIR"
  git clone "https://github.com/${ORG}/nwm-cal-mgr.git" "$CAL_DIR"
  cd "$CAL_DIR"
  git fetch --all --tags
  git checkout "$CAL_REF"
fi

echo "$LOG_PREFIX Installing nwm-cal-mgr from local clone"
if [[ "$EDITABLE" -eq 1 ]]; then
  python -m pip install -e .
else
  python -m pip install .
fi

echo "$LOG_PREFIX Installing mswm from ${ORG}/nwm-msw-mgr @ ${MSW_REF}"
python -m pip install \
  "mswm@git+https://github.com/${ORG}/nwm-msw-mgr.git@${MSW_REF}"

echo "$LOG_PREFIX Installing nwm_metrics from ${ORG}/nwm-eval-mgr @ ${EVAL_REF}"
python -m pip install \
  "nwm_metrics@git+https://github.com/${ORG}/nwm-eval-mgr.git@${EVAL_REF}#subdirectory=nwm_metrics"

echo "$LOG_PREFIX Installing ewts from ${ORG}/nwm-ewts @ ${EWTS_REF}"
python -m pip install \
  "ewts@git+https://github.com/${ORG}/nwm-ewts.git@${EWTS_REF}#subdirectory=runtime/python/ewts"

echo "$LOG_PREFIX Installation complete"
echo "$LOG_PREFIX Python: $(command -v python)"
echo "$LOG_PREFIX Pip   : $(command -v pip)"
```

</details>

### 2. Make the script executable

```bash
chmod +x install_nwm_cal_mgr.sh
```

### 3. Run the installer

Install everything from the default `development` branch:

```bash
./install_nwm_cal_mgr.sh
```

Install all repositories from the same branch, tag, or commit SHA:

```bash
./install_nwm_cal_mgr.sh --ref 3.1.2.0.1
```

Install `nwm-cal-mgr` in editable mode:

```bash
./install_nwm_cal_mgr.sh --editable
```

Use a different GitHub organization or fork:

```bash
./install_nwm_cal_mgr.sh --org myfork --ref feature-branch
```

Override the ref for a specific dependency:

```bash
./install_nwm_cal_mgr.sh --ref development --eval-ref feature/new-metrics
```

### Installer options

* `--work-dir <path>`
  Parent directory for the local `nwm-cal-mgr` clone.
  Default: current directory.

* `--venv-dir <path>`
  Virtual environment directory.
  Default: `./venv`.

* `--org <github_org>`
  GitHub organization or user for all repositories.
  Default: `ngwpc`.

* `--ref <git_ref>`
  Shared Git ref (branch, tag, or commit SHA) for all repositories.
  Default: `development`.

* `--cal-ref <git_ref>`
  Override ref for `nwm-cal-mgr`.

* `--msw-ref <git_ref>`
  Override ref for `nwm-msw-mgr`.

* `--eval-ref <git_ref>`
  Override ref for `nwm-eval-mgr`.

* `--ewts-ref <git_ref>`
  Override ref for `nwm-ewts`.

* `--editable`
  Install `nwm-cal-mgr` in editable mode.

### Ref precedence

If both shared and per-repository refs are provided, refs are resolved in the following order:

1. repository-specific ref (`--cal-ref`, `--msw-ref`, `--eval-ref`)
2. shared ref (`--ref`)
3. default `development`

---

## Manual installation

### 1. Create a Python virtual environment

```bash
mkdir -p [VENV_DIR]
cd [VENV_DIR]
/usr/bin/python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip
```

### 2. Clone `nwm-cal-mgr`

```bash
mkdir -p [WORK_DIR]
cd [WORK_DIR]
git clone -b development https://github.com/ngwpc/nwm-cal-mgr.git
```

### 3. Install `nwm-cal-mgr`

Install from the repository root:

```bash
pip install [WORK_DIR]/nwm-cal-mgr
```

For an editable install:

```bash
pip install -e [WORK_DIR]/nwm-cal-mgr
```

### 4. Install dependency `mswm`

Install directly from GitHub:

```bash
pip install "mswm@git+https://github.com/ngwpc/nwm-msw-mgr.git@development"
```

### 5. Install dependency `nwm_metrics`

Install the `nwm_metrics` package directly from GitHub:

```bash
pip install "nwm_metrics@git+https://github.com/ngwpc/nwm-eval-mgr.git@development#subdirectory=nwm_metrics"
```

### 6. Install dependency `ewts`
Install the `ewts` package directly from GitHub:

```bash
pip install "ewts@git+https://github.com/ngwpc/nwm-ewts.git@development#subdirectory=runtime/python/ewts"
```
---

## Verify installation

Installing `nwm-cal-mgr` also installs the calibration/validation CLI commands.

To confirm that the CLI commands are available:

```bash
source [VENV_DIR]/bin/activate
which calibration
which validation
which validation_iteration
```

You can also view the help for each command:

```bash
calibration --help
validation --help
validation_iteration --help
```
---

## Run calibration and validation

### Run MSWM

First, run model setup workflow manager (MSWM) to produce input files for calibration/validation. Refer to one of 
the sample config files in [MSWM](https://github.com/NGWPC/nwm-msw-mgr/tree/development/src/mswm/example_inputs) 
to set up your configuration for calibration/validation.

```bash
python -m mswm.manager build_calib <path_to_mswm_config>
```
Where `<path_to_mswm_config>` is the path to the MSWM configuration file. This will produce a set of input files for 
calibration/validation, including a config file for calibration to be used in the next step.

Note MSWM creates the input, output and log folders for calibration/validation runs based on configurations in 
the MSWM config file, e.g.:
- input: `kge_dds/noah_cfes/01123000/Input`
- output (calibration): `kge_dds/noah_cfes/01123000/Output/Calibration_Run`
- output (validation): `kge_dds/noah_cfes/01123000/Output/Validation_Run`
- logs: `kge_dds/noah_cfes/01123000/logs`

### Run calibration

```bash
calibration <path_to_calib_config>
```
Where `<path_to_calib_config>` is the path to the config file for calibration, which can be found in the log file from running MSWM.

Example:
```bash
calibration kge_dds/noah_cfes/01123000/Input/01123000_config_calib.yaml
```

### Run validation

```bash
validation <path_to_valid_control_config>
validation <path_to_valid_best_config>
```
where `<path_to_valid_control_config>` and `<path_to_valid_best_config>` are the config files for validation runs with 
the control/default parameters and the best parameters, respectively. These config files are produced at the end of calibration
(see the log file for paths to these files).

Example:
```bash
validation kge_dds/noah_cfes/01123000/Output/Validation_Run/01123000_config_valid_control.yaml
validation kge_dds/noah_cfes/01123000/Output/Validation_Run/01123000_config_valid_best.yaml
```

### Run validation for an alternative iteration
Optionally, you can run validation for an alternative iteration (i.e., not the control/default or the best) by providing 
the iteration number as an argument. This is useful when you want to check the performance of parameters from a specific 
calibration iteration over the calibration and validation periods.

```bash
validation_iteration <path_to_calib_config> <worker_ID> <iteration_number>
```
Where `<worker_ID>` refers to the middle part of the folder name for a specific calibration run. For example, if the 
calibration run folder is named `ngen_ulu2wno6_worker`, then the worker ID is `ulu2wno6`. Note here the config file for 
the calibration run (rather than the validation run) is used as the first argument.

Example:
```bash
# run validation for iteration 5 of the calibration run with worker ID "ulu2wno6"
validation_iteration kge_dds/noah_cfes/01123000/Input/01123000_config_calib.yaml ulu2wno6 5
```
---

## Docker Container

### Requirements

To build and run `nwm-cal-mgr` with Docker, you will need:

* Docker Engine

### Build

From the repository root, run `build_nwm_cal_mgr.sh` to build the container image:

```bash
./build_nwm_cal_mgr.sh
./build_nwm_cal_mgr.sh --ref development
```

### Container help

To display the container help message:

```bash
docker run nwm-cal-mgr --help
# or
docker run nwm-cal-mgr -h
```

This will print the available commands supported by the container CLI:

```text
Usage: run-nwm-cal-mgr.sh <command> <input_file> [worker_name iteration_number] [stdout_file]

COMMAND:
  mswm                 Run mswm to create inputs for calibration/validation.
  calibration          Run calibration.
  validation           Run validation.
  validation_iteration Run validation for a specific iteration; requires worker_name and iteration_number.

INPUT_FILE: Path to the configuration file required by the script.
WORKER_NAME: Required for validation_iteration.
ITERATION_NUMBER: Required for validation_iteration.
STDOUT_FILE: Optional path where script console output will be saved.

Examples:
  run-nwm-cal-mgr.sh mswm /path/to/mswm_config.yaml
  run-nwm-cal-mgr.sh calibration /path/to/calib_config.yaml
  run-nwm-cal-mgr.sh validation /path/to/valid_config.yaml /path/to/output.log
  run-nwm-cal-mgr.sh validation_iteration /path/to/calib_config.yaml worker1 5 /path/to/output.log
```

### Run calibration and validation in the container

When running a calibration workflow, you will typically need to mount local data and configuration files into the container.

- run MSWM to create inputs for calibration/validation:

  ```bash
  docker run \
    -v $(pwd):$(pwd) \
    -w $(pwd) \
    nwm-cal-mgr \
    mswm <path_to_mswm_config>
  ```

- run calibration:

  ```bash
  docker run \
    -v $(pwd):$(pwd) \
    -w $(pwd) \
    nwm-cal-mgr \
    calibration <path_to_calib_config>
  ```
- run validation control and best:

    ```bash
    docker run \
        -v $(pwd):$(pwd) \
        -w $(pwd) \
        nwm-cal-mgr \
        validation <path_to_valid_control_config>
    ```
    
    ```bash
    docker run \
        -v $(pwd):$(pwd) \
        -w $(pwd) \
        nwm-cal-mgr \
        validation <path_to_valid_best_config>
    ```

- run validation for a specific iteration:

  ```bash
  docker run \
    -v $(pwd):$(pwd) \
    -w $(pwd) \
    nwm-cal-mgr \
    validation_iteration <path_to_calib_config> <worker_ID> <iteration_number>
  ```  

- test the full calibration and validation workflow:

The helper script [`docker/run_full_calib_valid_workflow.sh`](docker/run_full_calib_valid_workflow.sh) can be used to 
run the full calibration and validation workflow in a single command. The script will run MSWM, calibration, and 
validation (control, best, and alternative iteration) sequentially.

```bash
cd [WORK_DIR]

# download the script
curl -L -O https://raw.githubusercontent.com/ngwpc/nwm-cal-mgr/development/docker/run_full_calib_valid_workflow.sh

# make the script executable
chmod +x run_full_calib_valid_workflow.sh

# check the script help message
./run_full_calib_valid_workflow.sh --help

# run the full workflow with default settings (basin 01123000, noah-owp-modular + cfe-s, 3 iterations)
./docker/run_full_calib_valid_workflow.sh

# run the full workflow with custom settings
./docker/run_full_calib_valid_workflow.sh \
    --basin 10310500 \
    --models "noah-owp-modular, cfe-x" \
    --formulation noah_cfex \
    --iterations 500

./docker/run_full_calib_valid_workflow.sh \
    -b 10310500 \
    -m "noah-owp-modular, cfe-x" \
    -f noah_cfex \
    -i 500

```

### Notes

* File paths provided to the container must correspond to paths visible from within the container.
* Any paths referenced in the configuration file must also be valid within the container environment.
* If your workflow requires access to external datasets, ensure the corresponding directories are mounted into the container using Docker volume mounts (`-v`).


---

## License

License information to be added.