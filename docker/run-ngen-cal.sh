#!/bin/bash



__usage="
Usage: $(basename $0) <operation> <input file>

Required args:
  <operation>         calibration operation, options: create_input, calibration, validation
  <input file>        path to input file for operation
"
CREATE_INPUT_SCRIPT="/ngen-app/ngen-python/lib/python3.10/site-packages/createInput/create_input.py"
CALIB_SCRIPT="/ngen-app/ngen-cal/python/runCalibValid/calibration.py"
VALID_SCRIPT="/ngen-app/ngen-cal/python/runCalibValid/validation.py"


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

if [[ $# -ne 2 ]]; then
    usage
fi

operation=${1}
input_file=${2}

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

  *)
    echo "ERROR: unknown operation selected"
    usage
    ;;
esac

exit_script 0 "INFO: Script complete!"
