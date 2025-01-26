# ------------------------------------------------
# Main Input Configuration File
#
# This file is used to create the input data and files to run calibration and validation.
# It contains three sections:
#    1. General
#    2. Calibration
#    3. DataFile
# ------------------------------------------------

[General]

# info from the server (optional - only need to be filled when running from GUI)
ngen_cerf = false
calibration_run_id = 206
auth_token = eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzI3MzgwNDg4LCJpYXQiOjE3MjcyOTQwODgsImp0aSI6IjI3NzY2NDk5YWFkZjQ4Y2NiNDk5YTU4NWJkZDJkZGRkIiwidXNlcl9pZCI6Miwic2NvcGUiOiJuZ2VuIn0.6bM9O3lyGjDxZ7B2suDP-Kq56cQZ_8ZnYKxjxsJqFMg

# Stream gage ID at basin outlet 
basin = 01123000

# List of models to include in the formulation 
# Note: t-route will be added if not selected; sloth will be added if cfe-s/cfe-x or lasam is selected.
# Currently modules can be selected from the following list (case insensitive, one module per process):
# -- Glacier or snow --: noah-owp-modular, snow-17, ueb (topoflow is being implemented)
# -- evapotranspiration --: pet, noah-owp-modular
# -- soil moisture --: smp, sft (note: currently only implemented for when cfe-s, cfe-x or lasam is selected)
# -- rainfall runoff --: cfe-s, cfe-x, topmodel, sac-sma, lasam
# -- routing --: t-route
#models = noah-owp-modular, cfe-x
#models = noah-owp-modular,ueb,topmodel,t-route
#models = noah-owp-modular,sft,cfe-s
models = noah-owp-modular,topmodel
#models = pet,ueb,cfe-s

# User defined formulation name (used to create folder for inputs/outputs; so no space in the name)
#formulation = noah_ueb_top
#formulation = noah_sft_cfes
formulation = noah_top

# Run name (currently only one option: calib)
run_type = calib

# Main directory to store input, output and other files  
main_dir = /home/yuqiong.liu/work/Gitlab/run

[Calibration]
# Optimizaition algorithm (options: dds, pso, gwo)
optimization_algorithm = DDS

# Algorithm parameters for PSO & GWO
# swarm_size is applicable to both PSO & GWO; c1, c2 & w are only applicable to PSO
swarm_size = 3
c1 = 2
c2 = 2
w = 0.7

# Objective function (options: kge,nse,nnse,nselog,corr,csi,pod,rmse,mae,rsr,far,pkbias,pkte,evbias,pbias,lseg_fdc,hseg_fdc)   
objective_function = kge

# Starting iteration number
start_iteration = 0

# Number of iterations01123000/PARAMS
number_iteration = 3

# Whether to restart calibration from a stopped iteration (0: Not; 1: Yes)
# currently only option is 0 (i.e., no restart)
restart = 0

# Simulation time period for calibration
calib_start_period = 2015-10-01 00:00:00
calib_end_period = 2017-09-30 23:00:00

# Evaluation time period for calibration (to exclude a warm-up period from simulation when calculating metrics)
calib_eval_start_period = 2016-10-01 00:00:00
calib_eval_end_period = 2017-09-30 23:00:00

# Simulation time period for validation
valid_start_period = 2014-10-01 00:00:00
valid_end_period = 2017-09-30 23:00:00

# Evaluation time period for validation
valid_eval_start_period = 2015-10-01 00:00:00
valid_eval_end_period = 2016-09-30 23:00:00

# Full evaluation time period (calibation + validation evaluation periods)
full_eval_start_period = 2015-10-01 00:00:00
full_eval_end_period = 2017-09-30 23:00:00

# Save streamflow output and plots at iterations
# 0 - no; 1 - yes, with iteration number attached to output file name
save_output_iter = 0
save_plot_iter = 0

# Iteration interval to save plots
save_plot_iter_freq = 1

# Streamflow threshold in cms for the calculation of categorical scores (optional)
# If not specified, categorical metrics will not be calculated (here 3.88 is 90% flow in cmsfor test basin 01123000)
streamflow_threshold = 3.88

# Streamflow station name used for the title of plots (optional)
station_name = "Little River Near Hanover, CT"

# Email address to receive the notification of run completion (optional) 
user_email = 

[DataFile]
# Diretory for forcing data 
forcing_dir = /home/yuqiong.liu/work/data/aorc_nwm/csv_basin_group1/Gage_01123000_new/

# Diretory for streamflow observation  
# If left blank or commented out, streamflow observations will be retrieved on the fly 
# from NWIS site during calibration and validation runs.
obs_dir = /home/yuqiong.liu/work/data/streamflow_obs/

# File path for NWM retreospective streamflow simulation
# If left lank or commented out, metrics for NWM retrospective simulation will not be calculated or 
# plotted during the validation runs (with best parameters or parameters from an alternative iteration).
nwmretro_file = /home/yuqiong.liu/work/data/nwmv3_retro_streamflow/01123000.csv

# Diretory for hydrofabric data   
hydrofab_file = /home/yuqiong.liu/work/data/gpkg_v2.2/CONUS/gages-01123000.gpkg

# Diretories for module BMI config files (if blank, ngen-cal will create these files)
topoflow_bmi_dir =
#noah-owp-modular_bmi_dir = /home/yuqiong.liu/work/Gitlab/run/kge_dds/noah_cfe/01123000/Input/noah_input
noah-owp-modular_bmi_dir = /home/yuqiong.liu/work/data/NEDS_files_new/01123000/PARAMS/USGS/Noah-OWP-Modular
#noah-owp-modular_bmi_dir =
snow-17_bmi_dir =
ueb_bmi_dir = /home/yuqiong.liu/work/data/NEDS_files_new/01123000/PARAMS/USGS/UEB
#ueb_bmi_dir = /home/yuqiong.liu/work/data/NEDS_files/ueb
#ueb_bmi_dir = 
pet_bmi_dir =
smp_bmi_dir = /home/yuqiong.liu/work/data/NEDS_files_new/01123000/PARAMS/USGS/SMP
sft_bmi_dir = /home/yuqiong.liu/work/data/NEDS_files_new/01123000/PARAMS/USGS/SFT
cfe-s_bmi_dir =
#cfe-s_bmi_dir = /home/yuqiong.liu/work/Gitlab/run/kge_dds/noah_cfe/01123000/Input/cfe_input
cfe-x_bmi_dir = 
#cfe-x_bmi_dir = /home/yuqiong.liu/work/Gitlab/run/kge_dds/noah_cfe.xaj/01123000/Input/cfe.xaj_input
topmodel_bmi_dir = /home/yuqiong.liu/work/data/NEDS_files_new/01123000/PARAMS/USGS/TopModel
sac-sma_bmi_dir = /home/yuqiong.liu/work/data/NEDS_files_new/01123000/PARAMS/USGS/Sac-SMA.copy
lasam_bmi_dir = /home/yuqiong.liu/work/data/NEDS_files_new/01123000/PARAMS/USGS/LASAM.copy
t-route_bmi_dir = /home/yuqiong.liu/work/data/NEDS_files_new/01123000/PARAMS/USGS/T-Route

# Special case for topmodel BMI files
# if topmodel_bmi_dir is not provided, then topmd_dir is needed to provide template BMI config files or Topmodel, 
# and ngen-cal will adjust the folder paths in these files to be consistent with the work directory setup
#topmd_dir = /home/yuqiong.liu/work/data/bmi_config/Topmodel_v2.2
#topmd_dir = /home/yuqiong.liu/work/data/NEDS_files_new/01123000/PARAMS/USGS/TopModel

# Diretory or file for constant/additional module parameters (currently applicable to noah, lasam, and ueb)
# these can be found in the ngne-cal source repo under ngne-cal/module_parameter_files
noah_parameter_dir = /home/yuqiong.liu/work/Gitlab/ngen-cal/module_parameter_files/noah-owp-modular
ueb_parameter_dir = /home/yuqiong.liu/work/Gitlab/ngen-cal/module_parameter_files/ueb
lasam_parameter_dir = /home/yuqiong.liu/work/Gitlab/ngen-cal/module_parameter_files/lasam
#lasam_soil_parameter_file = /home/yuqiong.liu/work/Gitlab/ngen-cal/module_parameter_files/lasam/vG_default_params.dat
#lasam_soil_class_file =  /home/yuqiong.liu/work/Gitlab/ngen-cal/module_parameter_files/lasam/lasam_soil_class.txt

# Path for model attributes file (to derive initial parameters for certain modules: CFE, NOM, SMP/SFT)
attributes_file = /home/yuqiong.liu/work/data/conus_model_attributes.parquet

# Path for calibration parameter file or folder that includes such files for individual modules
# These files contain the minimum, maximum, and initial values of parameters for the specified module(s)
# There are 3 options
# 1) Folder path with files in tab-delimited format for individual modules (flexible)
# 2) Folder path with files in comma-delimited format for individual modules (flexible)
# 3) File path with calibration parameters for all modules presented in a single file in fix-width format (typically not recommended)
calib_parameter_file = /home/yuqiong.liu/work/data/calib_params_tab_delimited
#calib_parameter_file = /home/yuqiong.liu/work/data/calib_params_combined/calib_params_CFE_NOM.txt

# Executable file for running ngen BMI
ngen_exe_file = /home/yuqiong.liu/work/Gitlab/ngen/cmake_build/ngen

# Library files for modules (can be left blank if module is not selected)
sloth_lib = /home/yuqiong.liu/work/Gitlab/ngen/extern/sloth/cmake_build/libslothmodel.so
cfe_lib = /home/yuqiong.liu/work/Gitlab/ngen/extern/cfe/cmake_build/libcfebmi.so
lasam_lib = /home/yuqiong.liu/work/Gitlab/ngen/extern/LASAM/cmake_build/liblasambmi.so
noah-owp-modular_lib = /home/yuqiong.liu/work/Gitlab/ngen/extern/noah-owp-modular/cmake_build/libsurfacebmi.so
pet_lib = /home/yuqiong.liu/work/Gitlab/ngen/extern/evapotranspiration/evapotranspiration/cmake_build/libpetbmi.so
sac-sma_lib = /home/yuqiong.liu/work/Gitlab/ngen/extern/sac-sma/cmake_build/libsacbmi.so
sft_lib = /home/yuqiong.liu/work/Gitlab/ngen/extern/SoilFreezeThaw/cmake_build/libsftbmi.so
smp_lib = /home/yuqiong.liu/work/Gitlab/ngen/extern/SoilMoistureProfiles/cmake_build/libsmpbmi.so
snow-17_lib = /home/yuqiong.liu/work/Gitlab/ngen/extern/snow17/cmake_build/libsnow17bmi.so
topmodel_lib = /home/yuqiong.liu/work/Gitlab/ngen/extern/topmodel/cmake_build/libtopmodelbmi.so
#ueb_lib = /home/yuqiong.liu/work/Gitlab/ueb_bmi/cmake_build/src/libbmiuebcxx.so 
ueb_lib = /home/yuqiong.liu/work/Gitlab/ngen/extern/ueb-bmi/cmake_build/src/libbmiuebcxx.so