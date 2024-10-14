#!/bin/bash



__usage="
Usage: $(basename $0) <operation> <input file> [<worker_name> <iteration>]

Required args:
  <operation>         calibration operation, options: create_input, calibration, validation, validation_iteration
  <input file>        path to input file for operation
Optional args (for validation_iteration):
  <worker_name>       name of the worker
  <iteration>         iteration number
"

function usage () {
    echo "$__usage"
    exit 1
}

function exit_script () {
    if [ -n "$2" ] ; then
        echo "$2"
    fi
    exit $1
}

if [[ $# -lt 2 ]]; then
    usage
fi

current_dir=$(dirname $(readlink -f $0))
source ${current_dir}/ngen-cal.env

if [[ -z "${NGENCERF_VENV_ROOT}" || -z "${NGEN_CAL_ROOT}" ]]; then
  echo "ERROR: ngen-cal.env is not setting required environment variables"
  usage
fi
echo "DEBUG: NGENCERF_VENV_ROOT: ${NGENCERF_VENV_ROOT}"
echo "DEBUG: NGEN_CAL_ROOT: ${NGEN_CAL_ROOT}"

CREATE_INPUT_SCRIPT="${NGENCERF_VENV_ROOT}/createInput/create_input.py"
CALIB_SCRIPT="${NGEN_CAL_ROOT}/calibration.py"
VALID_SCRIPT="${NGEN_CAL_ROOT}/validation.py"
VALID_ITERATION_SCRIPT="${NGEN_CAL_ROOT}/validation_iteration.py"

operation=${1}
input_file=${2}
worker_name=${3}
iteration=${4}

echo "DEBUG: input_file: ${input_file}"
if [ ! -f "${input_file}" ] ; then
    echo "WARNING: Input file [${input_file}] does not exist!"
fi

case $operation in

  "create_input")
    echo "DEBUG: operation: create_input"
    echo "DEBUG: command: python3 \"${CREATE_INPUT_SCRIPT}\" \"${input_file}\""
    python3 "${CREATE_INPUT_SCRIPT}" "${input_file}"
    ;;

  "calibration")
    echo "DEBUG: operation: calibration"
    echo "DEBUG: command: python3 \"${CALIB_SCRIPT}\" \"${input_file}\""
    python3 "${CALIB_SCRIPT}" "${input_file}"
    ;;

  "validation")
    echo "DEBUG: operation: validation"
    echo "DEBUG: command: python3 \"${VALID_SCRIPT}\" \"${input_file}\""
    python3 "${VALID_SCRIPT}" "${input_file}"
    ;;

    "validation_iteration")
    if [[ -z "$worker_name" || -z "$iteration" ]]; then
      echo "ERROR: validation_iteration requires worker_name and iteration arguments"
      usage
    fi
    echo "DEBUG: operation: validation_iteration"
    echo "DEBUG: command: python3 \"${VALID_ITERATION_SCRIPT}\" \"${input_file}\" \"${worker_name}\" \"${iteration}\""
    python3 "${VALID_ITERATION_SCRIPT}" "${input_file}" "${worker_name}" "${iteration}"
    ;;

  *)
    echo "ERROR: unknown operation selected"
    usage
    ;;
esac

exit_script 0 "INFO: Script complete!"
