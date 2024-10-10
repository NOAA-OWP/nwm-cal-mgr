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
CREATE_INPUT_SCRIPT="/ngen-app/ngen-python/lib/python3.10/site-packages/createInput/create_input.py"
CALIB_SCRIPT="/ngen-app/ngen-cal/python/runCalibValid/calibration.py"
VALID_SCRIPT="/ngen-app/ngen-cal/python/runCalibValid/validation.py"
VALID_ITERATION_SCRIPT="/ngen-app/ngen-cal/python/runCalibValid/validation_iteration.py"


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
