#!/bin/bash
# Self-contained script to run the full calibration and validation workflow, using an nwm-cal-mgr docker image from GHCR: 
#     https://github.com/NGWPC/nwm-cal-mgr/pkgs/container/nwm-cal-mgr 
#
# Run "./run_full_calib_valid_workflow.sh --help" for usage


set -euo pipefail

#=============================================================
# Get arguments from command line to override default values
#=============================================================

# default values for optional args
BASIN="01123000"
DOMAIN="conus"
MODELS="noah-owp-modular, cfe-s"
FORMULATION="noah_cfes"
ITERATIONS=3
ALT_ITERATION=1

WORK_DIR="$(pwd)/calib"
IMAGE_TAG="pr-79-build"
PULL_IMAGE=false
RUN_ALT_ITERATION=false

usage() {
    cat <<EOF
Overview:
    Self-contained script to run the full calibration and validation workflow, using an nwm-cal-mgr docker image from GHCR: 
        https://github.com/NGWPC/nwm-cal-mgr/pkgs/container/nwm-cal-mgr 

    The workflow includes the following steps:
    - MSWM to generate input files for calibration and validation
    - Calibration using the generated input files
    - Validation using the default parameters
    - Validation using the best parameters from calibration
    - Validation using the parameters from an alternative iteration during calibration (optional)

Notes: 
    This script requires access to http://edfs.test.nextgenwaterprediction.com/ API to fetch the geopackage
    for the basin. Alternatively, you can manually download the geopackage for the basin and then provide its path
    in the [DataFile] section of the MSWM configuration file in the respective code block below, e.g.,
            hydrofab_file = $(pwd)/hydrofabric/{basin}.gpkg

    The code block for creating MSWM configuration file can be modified to update additional settings (e.g., 
    calibration and validation periods, objective function, optimization algorithm, etc.) as needed.

    The code block for creating calibration parameter files can be modified to update the parameter ranges and 
    initial values for each module as needed.

Usage:
  $0 [options]

Options:
  -d, --domain DOMAIN, domain name (default: conus)
  -m, --models MODELS, comma-separated list of models (default: noah-owp-modular, cfe-s)
  -f, --formulation FORMULATION, user specified formulation name (default: noah_cfes)
  -b, --basin BASIN, basin ID (default: 01123000)
  -i, --iterations ITERATIONS, number of calibration iterations (default: 3)
  -a, --alt_iteration ALT_ITERATION, alternative iteration number (default: 1)
  -w, --workdir WORK_DIR, working directory (default: $(pwd)/calib)
  -t, --image-tag IMAGE_TAG, docker image tag (default: pr-79-build)
  -p, --pull-image, pull the docker image before running (regardless of whether it exists locally)
  -r, --run-alt-iteration, run validation for the alternative iteration
  -h, --help, display this help message and exit

Examples:

  # Use defaults (calibration and validation for basin 01123000 with noah_cfes formulation)
  $0

  # Short options calibration and validation for basin 10310500 with noah_cfex formulation)
  $0 -b 10310500 -f noah_cfex -m "noah-owp-modular, cfe-s" 

  # Long options (calibration and validation for basin 10310500 with noah_cfex formulation)
  $0 --basin 10310500 --models "noah-owp-modular, cfe-x" --formulation noah_cfex

EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--domain)
            [[ $# -ge 2 ]] || { echo "Missing value for $1"; exit 1; }
            DOMAIN="$2"
            shift 2
            ;;
        -m|--models)
            [[ $# -ge 2 ]] || { echo "Missing value for $1"; exit 1; }
            MODELS="$2"
            shift 2
            ;;
        -f|--formulation)
            [[ $# -ge 2 ]] || { echo "Missing value for $1"; exit 1; }
            FORMULATION="$2"
            shift 2
            ;;
        -b|--basin)
            [[ $# -ge 2 ]] || { echo "Missing value for $1"; exit 1; }
            BASIN="$2"
            shift 2
            ;;
        -i|--iterations)
            [[ $# -ge 2 ]] || { echo "Missing value for $1"; exit 1; }
            ITERATIONS="$2"
            shift 2
            ;;
        -a|--alt_iteration)
            [[ $# -ge 2 ]] || { echo "Missing value for $1"; exit 1; }
            ALT_ITERATION="$2"
            shift 2
            ;;
        -w|--workdir)
            [[ $# -ge 2 ]] || { echo "Missing value for $1"; exit 1; }
            WORK_DIR="$2"
            shift 2
            ;;
        -t|--image-tag)
            [[ $# -ge 2 ]] || { echo "Missing value for $1"; exit 1; }
            IMAGE_TAG="$2"
            shift 2
            ;;
        -p|--pull-image)
            PULL_IMAGE=true
            shift
            ;;
        -r|--run-alt-iteration)
            RUN_ALT_ITERATION=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

IMAGE="ghcr.io/ngwpc/nwm-cal-mgr"
echo "DOMAIN      = $DOMAIN"
echo "MODELS      = $MODELS"
echo "FORMULATION = $FORMULATION"
echo "BASIN       = $BASIN"
echo "ITERATIONS  = $ITERATIONS"
echo "ALT_ITERATION = $ALT_ITERATION"
echo "RUN_ALT_ITERATION = $RUN_ALT_ITERATION"
echo "WORK_DIR    = $WORK_DIR"
echo "IMAGE       = $IMAGE:$IMAGE_TAG"
echo "PULL_IMAGE  = $PULL_IMAGE"

#=============================================================
# Create calibration parameter files for each module
#=============================================================
CALIB_PARAM_FILES="$(pwd)/calib_params_files"
mkdir -p "$CALIB_PARAM_FILES"

# noah-owp-modular
PARAM_FILE_NOM="${CALIB_PARAM_FILES}/calib_params_noah-owp-modular.csv"
if [[ "$MODELS" == *"noah-owp-modular"* && ! -f "$PARAM_FILE_NOM" ]]; then
    cat > "$PARAM_FILE_NOM" <<EOF
param	min	max	init
MFSNO	0.5	4	2
CWP	0.09	0.36	0.18
VCMX25	24	112	52.2
MP	3.6	12.6	9.7
RSURF_SNOW	0.136	100	49.2
RSURF_EXP	1	6	4.84
SCAMAX	0.7	1	0.89
EOF
fi

# cfe-s
PARAM_FILE_CFES="${CALIB_PARAM_FILES}/calib_params_cfe-s.csv"
if [[ "$MODELS" == *"cfe-s"* && ! -f "$PARAM_FILE_CFES" ]]; then
    cat > "$PARAM_FILE_CFES" <<EOF
param	min	max	init
b	2	15	7.272
satdk	1.950e-07	0.001	5.231e-06
satpsi	0.036	0.955	0.163
slope	5.980e-05	1	0.021
maxsmc	0.16	0.58	0.48
wltsmc	0.05	0.3	0.079
max_gw_storage	0.01	0.25	0.034
Cgw	1.800e-06	0.002	0.005
expon	1	8	6
Kn	0	1	0.003
Klf	0	1	0.01
refkdt	0.1	4	2
EOF
fi

# cfe-x
PARAM_FILE_CFEX="${CALIB_PARAM_FILES}/calib_params_cfe-x.csv"
if [[ "$MODELS" == *"cfe-x"* && ! -f "$PARAM_FILE_CFEX" ]]; then
    cat > "$PARAM_FILE_CFEX" <<EOF
param	min	max	init
a_Xinanjiang_inflection_point_parameter	-0.5	0.5	-0.234
b_Xinanjiang_shape_parameter	0.01	10	0.807
x_Xinanjiang_shape_parameter	0.01	10	0.105
b	2	15	7.163
satdk	1.950e-07	0.001	8.334e-06
satpsi	0.036	0.955	0.111
slope	5.980e-05	1	0.02
maxsmc	0.16	0.58	0.462
wltsmc	0.05	0.3	0.068
max_gw_storage	0.01	0.25	0.034
Cgw	1.800e-06	0.002	0.005
expon	1	8	6
Kn	0	1	0.003
Klf	0	1	0.01
refkdt	0.1	4	2
EOF
fi

# lasam
PARAM_FILE_LASAM="${CALIB_PARAM_FILES}/calib_params_lasam.csv"
if [[ "$MODELS" == *"lasam"* && ! -f "$PARAM_FILE_LASAM" ]]; then
    cat > "$PARAM_FILE_LASAM" <<EOF
param	min	max	init
smcmin	0.01	0.15	0.095
smcmax	0.3	0.8	0.41
van_genuchten_alpha	0.001	0.3	0.019
van_genuchten_n	1.01	3	1.31
hydraulic_conductivity	0.001	100	0.26
ponded_depth_max	0	5	1.1
field_capacity	10.3	516.6	340.9
EOF
fi

# sac-sma
PARAM_FILE_SACSMA="${CALIB_PARAM_FILES}/calib_params_sac-sma.csv"
if [[ "$MODELS" == *"sac-sma"* && ! -f "$PARAM_FILE_SACSMA" ]]; then
    cat > "$PARAM_FILE_SACSMA" <<EOF
param	min	max	init
uztwm	25	125	68.115
uzfwm	10	100	51.071
lztwm	75	300	98.923
lzfsm	15	300	9.829
lzfpm	40	600	83.205
adimp	0	0.2	0
uzk	0.2	0.5	0.396
lzpk	0.001	0.015	0.017
lzsk	0.03	0.2	0.144
zperc	20	300	82.283
rexp	1.4	3.5	1.802
pctim	0	0.05	0
pfree	0	0.5	0.147
riva	0	0.2	0
side	0	0.2	0
EOF
fi

# snow-17
PARAM_FILE_SNOW17="${CALIB_PARAM_FILES}/calib_params_snow-17.csv"
if [[ "$MODELS" == *"snow-17"* && ! -f "$PARAM_FILE_SNOW17" ]]; then
    cat > "$PARAM_FILE_SNOW17" <<EOF
param	min	max	init
mfmax	0.1	2.2	1.431
uadj	0.01	0.2	0.033
si	0	10000	500
mfmin	0.01	0.6	0.403
scf	0.9	1.8	1.1
nmf	0.01	0.3	0.15
tipm	0	1	0.1
pxtemp	0.5	5	1
plwhc	0.01	0.3	0.03
daygm	0	0.5	0
EOF
fi

# topmodel
PARAM_FILE_TOPMODEL="${CALIB_PARAM_FILES}/calib_params_topmodel.csv"
if [[ "$MODELS" == *"topmodel"* && ! -f "$PARAM_FILE_TOPMODEL" ]]; then
    cat > "$PARAM_FILE_TOPMODEL" <<EOF
param	min	max	init
szm	0.001	0.25	0.013
t0	0	1.000e-04	7.500e-05
td	0.001	40	20
chv	50	2000	1000
rv	50	2000	1000
srmax	0.005	0.05	0.04
sr0	0	0.1	0
xk0	1.000e-04	0.2	2
EOF
fi

# topoflow-glacier
PARAM_FILE_TFG="${CALIB_PARAM_FILES}/calib_params_topoflow-glacier.csv"
if [[ "$MODELS" == *"topoflow-glacier"* && ! -f "$PARAM_FILE_TFG" ]]; then
    cat > "$PARAM_FILE_TFG" <<EOF
param	min	max	init
T_rain_snow	0.5	5.0	1.0
EOF
fi

# ueb
PARAM_FILE_UEB="${CALIB_PARAM_FILES}/calib_params_ueb.csv"
if [[ "$MODELS" == *"ueb"* && ! -f "$PARAM_FILE_UEB" ]]; then
    cat > "$PARAM_FILE_UEB" <<EOF
param	min	max	init
df	0.5	6	1
cc	0	0.8	0.4
hcan	0	10	5
lai	0	4	2
subalb	0.25	0.7	0.25
ems	0.98	0.99	0.99
cg	2.09	2.12	2.09
zo	2.000e-04	0.014	0.01
rho	100	600	300
rhog	1100	1700	1700
Ks	0	20	20
de	0.1	0.4	0.1
avo	0.85	0.95	0.95
apr	30000	101325	50000
EOF
fi

#=============================================================
# Create configuration file for MSWM
#=============================================================
CONFIG_FILE="${WORK_DIR}/mswm_config_${BASIN}.ini"
mkdir -p "$(dirname "$CONFIG_FILE")"

cat > "$CONFIG_FILE" <<EOF
[General]
domain = ${DOMAIN}
basin = ${BASIN}
models = ${MODELS}
formulation = ${FORMULATION}
is_aet_rootzone = true
run_type = calibration
main_dir = ${WORK_DIR}
output_swe = true
output_sm = false

[Calibration]
calibration_run_id = 
ngen_cerf = false
optimization_algorithm = dds
swarm_size = 4
c1 = 2.0
c2 = 2.0
w = 0.7
r = 0
objective_function = kge
start_iteration = 0
number_iteration = ${ITERATIONS}
restart = 0
calib_output_vars = True
valid_output_vars = True
calib_start_period = 2013-10-01 00:00:00
calib_end_period = 2014-09-30 23:00:00
calib_eval_start_period = 2013-04-01 00:00:00
calib_eval_end_period = 2014-09-30 23:00:00
valid_start_period = 2013-10-01 00:00:00
valid_end_period = 2014-12-31 23:00:00
valid_eval_start_period = 2014-10-01 00:00:00
valid_eval_end_period = 2014-12-31 23:00:00
full_eval_start_period = 2014-04-01 00:00:00
full_eval_end_period = 2014-12-31 23:00:00
save_output_iter = 0
save_plot_iter = 0
save_plot_iter_freq = 1
threshold_categorical = 0.9
threshold_categorical_type = quantile
threshold_event = 0.9
threshold_event_type = quantile
calib_parameter_file = ${CALIB_PARAM_FILES}

[Forcing]
forcing_provider = bmi
root_dir = /ngencerf-app/runtime_data
forcing_template_dir = /ngen-app/ngen-forcing/NextGen_Forcings_Engine_BMI/BMI_NextGen_Configs/config_templates/
forcing_configuration = aorc

[DataFile]
noah_parameter_dir = /ngen-app/ngen-python/lib/python3.11/site-packages/mswm/module_parameter_files/noah-owp-modular
ueb_parameter_dir = /ngen-app/ngen-python/lib/python3.11/site-packages/mswm/module_parameter_files/ueb
lasam_parameter_dir = /ngen-app/ngen-python/lib/python3.11/site-packages/mswm/module_parameter_files/lasam
lstm_parameter_dir = /ngen-app/ngen-python/lib/python3.11/site-packages/mswm/module_parameter_files/lstm

ngen_exe_file = /ngen-app/ngen/cmake_build/ngen
sloth_lib = /ngen-app/ngen/extern/sloth/cmake_build/libslothmodel.so
cfe_lib = /ngen-app/ngen/extern/cfe/cmake_build/libcfebmi.so
lasam_lib = /ngen-app/ngen/extern/LASAM/cmake_build/liblasambmi.so
noah_owp_modular_lib = /ngen-app/ngen/extern/noah-owp-modular/cmake_build/libsurfacebmi.so
pet_lib = /ngen-app/ngen/extern/evapotranspiration/evapotranspiration/cmake_build/libpetbmi.so
sac_sma_lib = /ngen-app/ngen/extern/sac-sma/cmake_build/libsacbmi.so
sft_lib = /ngen-app/ngen/extern/SoilFreezeThaw/cmake_build/libsftbmi.so
smp_lib = /ngen-app/ngen/extern/SoilMoistureProfiles/cmake_build/libsmpbmi.so
snow_17_lib = /ngen-app/ngen/extern/snow17/cmake_build/libsnow17bmi.so
topmodel_lib = /ngen-app/ngen/extern/topmodel/cmake_build/libtopmodelbmi.so
ueb_lib = /ngen-app/ngen/extern/ueb-bmi/cmake_build/src/libbmiuebcxx.so

[Parallel]
parallel_ngen_exe = /ngen-app/ngen/cmake_build/ngen
partition_generator_exe = /ngen-app/ngen/cmake_build/partitionGenerator
nprocs = 1
EOF

#=============================================================
# Docker run function
#=============================================================
mkdir -p $(pwd)/runtime_data
docker_run() {
  local command=$1
  shift

  echo -e "\n============================================================"
  echo "Running: $command $@"
  echo "============================================================"

  docker run \
    --user "$(id -u):$(id -g)" \
    -v "$(pwd):$(pwd)" \
    -v "$HOME":"$HOME" \
    -v "$(pwd)/runtime_data:/ngencerf-app/runtime_data" \
    -w "$(pwd)" \
    "$IMAGE:$IMAGE_TAG" \
    "$command" "$@"
}


wait_for_file() {
    local file="$1"
    while [ ! -f "$file" ]; do
        sleep 5
    done
}

#=====================================================================
# Check if the output directory already exists and prompt for deletion
#=====================================================================
current_dir="${WORK_DIR}/kge_dds/$FORMULATION/$BASIN"

if [ -d "$current_dir" ]; then
    read -r -p "Directory '$current_dir' already exists. Delete it? [y/N] " reply

    case "$reply" in
        [yY]|[yY][eE][sS])
            echo "Removing existing directory: $current_dir"
            rm -rf "$current_dir"
            ;;
        *)
            echo "Keeping existing directory. Exiting."
            exit 1
            ;;
    esac
fi

#=====================================================================
# run the full workflow, including MSWM, calibration, validation steps
#=====================================================================

if [ "$PULL_IMAGE" = true ]; then
    echo "Pulling docker image $IMAGE:$IMAGE_TAG..."
    docker pull "$IMAGE:$IMAGE_TAG"
fi

# run MSWM to generate input files for calibration and validation
docker_run mswm "$CONFIG_FILE"

# run calibration
CALIB_CFG="${WORK_DIR}/kge_dds/$FORMULATION/$BASIN/Input/${BASIN}_config_calib.yaml"
wait_for_file "$CALIB_CFG"
docker_run calibration "$CALIB_CFG"

# validation with control/default parameters
VALID_CONTROL="${WORK_DIR}/kge_dds/$FORMULATION/$BASIN/Output/Validation_Run/${BASIN}_config_valid_control.yaml"
wait_for_file "$VALID_CONTROL"
docker_run validation "$VALID_CONTROL"

# validation with best parameters from calibration
VALID_BEST="${WORK_DIR}/kge_dds/$FORMULATION/$BASIN/Output/Validation_Run/${BASIN}_config_valid_best.yaml"
VALID_CONTROL_METRICS="${WORK_DIR}/kge_dds/$FORMULATION/$BASIN/Output/Validation_Run/${BASIN}_metrics_valid_control.csv"
wait_for_file "$VALID_BEST"
wait_for_file "$VALID_CONTROL_METRICS"
docker_run validation "$VALID_BEST"

# validation with parameters from alternative iteration during calibration
if [ "$RUN_ALT_ITERATION" = true ]; then
    dir=$(find "${WORK_DIR}/kge_dds/$FORMULATION/$BASIN/Output/Calibration_Run" -maxdepth 1 -type d -name 'ngen_*_worker' | head -1)
    id=${dir##*/ngen_}
    id=${id%_worker}

    VALID_BEST_METRICS="${WORK_DIR}/kge_dds/$FORMULATION/$BASIN/Output/Validation_Run/${BASIN}_metrics_valid_best.csv"
    wait_for_file "$VALID_BEST_METRICS"
    docker_run validation_iteration $CALIB_CFG $id $ALT_ITERATION
fi