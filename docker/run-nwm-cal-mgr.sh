#!/bin/bash

LOG_PREFIX="[run-nwm-cal-mgr.sh]"

# This shell script lives in the nwm-cal-mgr repo.
# It is used by ngenCERF runtime containers to invoke nwm-cal-mgr scripts.

VALID_COMMANDS=("mswm" "calibration" "validation" "validation_iteration")

# Set the umask so files and directories are created with 777 permissions
umask 000

show_help() {
  echo "Usage: $(basename "$0") <command> <input_file> [worker_name iteration_number] [stdout_file]"
  echo ""
  echo "COMMAND:"
  echo "  mswm                 Run mswm to create inputs for calibration/validation."
  echo "  calibration          Run calibration."
  echo "  validation           Run validation."
  echo "  validation_iteration Run validation for a specific iteration; requires worker_name and iteration_number."
  echo ""
  echo "INPUT_FILE: Path to the configuration file required by the script."
  echo "WORKER_NAME: Required for validation_iteration."
  echo "ITERATION_NUMBER: Required for validation_iteration."
  echo "STDOUT_FILE: Optional path where script console output will be saved."
  echo ""
  echo "Examples:"
  echo "  $(basename "$0") mswm /path/to/mswm_config.yaml"
  echo "  $(basename "$0") calibration /path/to/calib_config.yaml"
  echo "  $(basename "$0") validation /path/to/valid_config.yaml /path/to/output.log"
  echo "  $(basename "$0") validation_iteration /path/to/calib_config.yaml worker1 5 /path/to/output.log"
  echo ""
  exit 1
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  show_help
  exit 0
fi

if [ -z "${1:-}" ]; then
  echo "$LOG_PREFIX Error: No script command provided. Allowable commands are: ${VALID_COMMANDS[*]}."
  show_help
  exit 1
fi

SCRIPT_COMMAND=$1
shift 1

case "$SCRIPT_COMMAND" in
  "mswm"|"calibration"|"validation")
    REQUIRED_ARGS=1
    ;;
  "validation_iteration")
    REQUIRED_ARGS=3
    ;;
  *)
    echo "$LOG_PREFIX Error: Invalid script command: '$SCRIPT_COMMAND'. Allowable commands are: ${VALID_COMMANDS[*]}."
    show_help
    ;;
esac

# Check if the correct number of arguments are provided for the selected command
if [ $# -lt "$REQUIRED_ARGS" ]; then
  echo "$LOG_PREFIX Error: Insufficient arguments. $SCRIPT_COMMAND requires $REQUIRED_ARGS arguments."
  show_help
fi

# Get the input file and additional parameters for validation_iteration
INPUT_FILE=$1
shift 1

echo "$LOG_PREFIX Input file: $INPUT_FILE"
if [ ! -f "$INPUT_FILE" ]; then
  echo "$LOG_PREFIX Error: Input file not found: $INPUT_FILE"
  exit 1
fi

if [ "$SCRIPT_COMMAND" == "validation_iteration" ]; then
  WORKER_NAME=$1
  ITERATION_NUMBER=$2
  shift 2

  echo "$LOG_PREFIX Worker name: $WORKER_NAME"
  echo "$LOG_PREFIX Iteration number: $ITERATION_NUMBER"
fi

STDOUT_FILE=""
if [ $# -ge 1 ]; then
  STDOUT_FILE=$1
  shift 1

  echo "$LOG_PREFIX Output file: $STDOUT_FILE"

  STDOUT_DIR=$(dirname "$STDOUT_FILE")
  mkdir --parents "$STDOUT_DIR"
fi

if [ $# -gt 0 ]; then
  echo "$LOG_PREFIX Error: Unexpected extra arguments: $*"
  show_help
fi

echo "$LOG_PREFIX Running $SCRIPT_COMMAND with input file: $INPUT_FILE"

if [ "$SCRIPT_COMMAND" == "mswm" ]; then
  if [ -z "$STDOUT_FILE" ]; then
    python -m mswm.manager build_calib "$INPUT_FILE"
  else
    python -m mswm.manager build_calib "$INPUT_FILE" > "$STDOUT_FILE" 2>&1
  fi
elif [ "$SCRIPT_COMMAND" == "validation_iteration" ]; then
  if [ -z "$STDOUT_FILE" ]; then
    "$SCRIPT_COMMAND" "$INPUT_FILE" "$WORKER_NAME" "$ITERATION_NUMBER"
  else
    "$SCRIPT_COMMAND" "$INPUT_FILE" "$WORKER_NAME" "$ITERATION_NUMBER" > "$STDOUT_FILE" 2>&1
  fi
else
  if [ -z "$STDOUT_FILE" ]; then
    "$SCRIPT_COMMAND" "$INPUT_FILE"
  else
    "$SCRIPT_COMMAND" "$INPUT_FILE" > "$STDOUT_FILE" 2>&1
  fi
fi

python_exit_code=$?

if [ $python_exit_code -ne 0 ]; then
  echo "$LOG_PREFIX $SCRIPT_COMMAND exited with code $python_exit_code"
fi

if [ -n "$STDOUT_FILE" ]; then
  echo "$LOG_PREFIX Output from running $SCRIPT_COMMAND"
  echo "-------------- start of $STDOUT_FILE -----------------------------"
  cat "$STDOUT_FILE"
  echo "---------------- end of $STDOUT_FILE -----------------------------"
fi

echo "$LOG_PREFIX Done running $SCRIPT_COMMAND"

exit $python_exit_code
