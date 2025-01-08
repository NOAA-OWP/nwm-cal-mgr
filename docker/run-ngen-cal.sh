#!/bin/bash

# Define valid commands
VALID_COMMANDS=("calibration" "validation" "validation_iteration" "create_input")

# This shell script lives in the ngen-cal repo.  It is used by CerfServer when calling ngen-cal

# It is used by CerfServer directly when running in LOCAL mode.
# It is used by the ngen-cal docker container when the server is running in DOCKER or PARALLEL_WORKS mode.

CALIB_SCRIPT=/ngen-app/ngen-cal/python/runCalibValid/calibration.py
VALID_SCRIPT=/ngen-app/ngen-cal/python/runCalibValid/validation.py
VALID_ITERATION_SCRIPT=/ngen-app/ngen-cal/python/runCalibValid/validation_iteration.py
CREATE_INPUT_SCRIPT=/ngen-app/ngen-python/lib/python3.10/site-packages/createInput/create_input.py

# Set the umask so files and directories are created with 777 permissions
umask 000

# Function to display help message
show_help() {
  echo "Usage: $(basename "$0") <command> <input_file> [worker_name iteration_number] [stdout_file] [venv_path]"
  echo ""
  echo "COMMAND:"
  echo "  calibration          Run calibration script."
  echo "  validation           Run validation script."
  echo "  validation_iteration Run validation iteration script (requires worker_name and iteration_number)."
  echo "  create_input         Run create_input script."
  echo ""
  echo "INPUT_FILE: Path to the input file required by the script."
  echo "WORKER_NAME: (Required for validation_iteration) Name of the worker."
  echo "ITERATION_NUMBER: (Required for validation_iteration) Iteration number."
  echo "STDOUT_FILE (optional): Path to the stdout file where the script's console output will be saved.  Used when running in LOCAL or DOCKER environment"
  echo "VENV_PATH (optional): Path to the Python virtual environment.  Used when running in the LOCAL environment."
  echo ""
  echo "Examples:"
  echo "  $(basename "$0") calibration /path/to/input.csv"
  echo "  $(basename "$0") validation /path/to/input.csv /path/to/output.log"
  echo "  $(basename "$0") validation_iteration /path/to/input.csv worker1 5 /path/to/output.log /path/to/venv"
  echo ""
  exit 1
}

# Show help if the user requests it with --help or -h
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  show_help
fi

# Check if the command for the script is provided as the first argument
if [ -z "$1" ]; then
  echo "Error: No script command provided. Allowable commands are: ${VALID_COMMANDS[*]}."
  show_help
fi

# Get the script command and select the corresponding script path
SCRIPT_COMMAND=$1
shift 1

case "$SCRIPT_COMMAND" in
  "calibration")
    SCRIPT_PATH=$CALIB_SCRIPT
    REQUIRED_ARGS=1
    ;;
  "validation")
    SCRIPT_PATH=$VALID_SCRIPT
    REQUIRED_ARGS=1
    ;;
  "validation_iteration")
    SCRIPT_PATH=$VALID_ITERATION_SCRIPT
    REQUIRED_ARGS=3
    ;;
  "create_input")
    SCRIPT_PATH=$CREATE_INPUT_SCRIPT
    REQUIRED_ARGS=1
    ;;
  *)
    echo "Error: Invalid script command: '$SCRIPT_COMMAND'. Allowable commands are: ${VALID_COMMANDS[*]}."
    show_help
    ;;
esac

# Check if the selected script exists
if [ ! -f "$SCRIPT_PATH" ]; then
  echo "Error: Script not found at $SCRIPT_PATH"
  exit 1
fi

# Check if the correct number of arguments are provided for the selected command
if [ $# -lt $REQUIRED_ARGS ]; then
  echo "Error: Insufficient arguments. $SCRIPT_COMMAND requires $REQUIRED_ARGS arguments."
  show_help
fi

# Get the input file and additional parameters for validation_iteration
INPUT_FILE=$1
shift 1
echo "        Input file: $INPUT_FILE"

if [ "$SCRIPT_COMMAND" == "validation_iteration" ]; then
  WORKER_NAME=$1
  ITERATION_NUMBER=$2
  echo "           Worker name: $WORKER_NAME"
  echo "     Iteration number: $ITERATION_NUMBER"
  shift 2
fi

# Check if the output file and venv path are provided
STDOUT_FILE=""
VENV_PATH=""

if [ $# -ge 1 ]; then
  STDOUT_FILE=$1
  echo "       Output file: $STDOUT_FILE"

  # Create output directory if it doesn't exist
  STDOUT_DIR=$(dirname "$STDOUT_FILE")
  if [ ! -d "$STDOUT_DIR" ]; then
    mkdir --parents "$STDOUT_DIR"
  fi

  shift 1
fi

if [ $# -ge 1 ]; then
  VENV_PATH=$1
  echo "Virtual environment: $VENV_PATH"
  shift 1
fi

# Activate the virtual environment if provided
if [ -n "$VENV_PATH" ]; then
  if [ -d "$VENV_PATH/bin" ]; then
    source "$VENV_PATH/bin/activate"
  else
    echo "Error: Virtual environment path '$VENV_PATH' is invalid."
    exit 1
  fi
else
  echo "No virtual environment provided, running with default Python environment."
fi

# Run the Python script, redirecting its output if an output file is provided
echo "   Running $(basename "$SCRIPT_PATH") with input file: $INPUT_FILE"
if [ "$SCRIPT_COMMAND" == "validation_iteration" ]; then
  if [ -z "$STDOUT_FILE" ]; then
    python "$SCRIPT_PATH" "$INPUT_FILE" "$WORKER_NAME" "$ITERATION_NUMBER"
  else
    python "$SCRIPT_PATH" "$INPUT_FILE" "$WORKER_NAME" "$ITERATION_NUMBER" &> "$STDOUT_FILE" 2>&1
  fi
else
  if [ -z "$STDOUT_FILE" ]; then
    python "$SCRIPT_PATH" "$INPUT_FILE"
  else
    python "$SCRIPT_PATH" "$INPUT_FILE" > "$STDOUT_FILE" 2>&1
  fi
fi

python_exit_code=$?
if [ $python_exit_code -ne 0 ]; then
  echo "$(basename "$SCRIPT_PATH") exited with code $python_exit_code"
fi

# Display output if redirected to a file
if [ -n "$STDOUT_FILE" ]; then
  echo "Output from running $(basename "$SCRIPT_PATH")"
  echo "-------------- start of $STDOUT_FILE -----------------------------"
  cat "$STDOUT_FILE"
  echo "---------------- end of $STDOUT_FILE -----------------------------"
fi

echo "Done running $(basename "$SCRIPT_PATH")"

exit $python_exit_code
