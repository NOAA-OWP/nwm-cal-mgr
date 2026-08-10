# Installation instructions

Instructions on how to install, configure, and run calibration/validation are given below, 
where [VENV_ROOT] and [NWM_ROOT] refer to the directory to install python venv and nwm-cal-mgr
in your local workspace, respectively.

1. clone nwm-cal-mgr from Github

```bash
cd [NWM_ROOT]
git clone -b development --recurse-submodules https://github.com/NGWPC/nwm-cal-mgr.git
```

2. create python venv

```bash
cd [VENV_ROOT]
/usr/bin/python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
```
3. install **nwm-cal-mgr** package (includes calib, config, and CLI executables)

```bash
cd [NWM_ROOT]/nwm-cal-mgr
pip install . #or use "pip install -e ." to install the package as an editable
```

4. install dependency **mswm**

- clone mswm
```bash
cd [NWM_ROOT]
git clone -b development --recurse-submodules https://github.com/NGWPC/nwm-msw-mgr.git
```

- install mswm
```bash
cd [NWM_ROOT]/nwm-msw-mgr
pip install .
```

### Usage

After installation, the scripts can be executed in two ways:
- As CLI commands: `calibration`, `validation`, `validation_iteration`
- Directly with Python: `python [NWM_ROOT]/nwm-cal-mgr/python/[script].py`

1) set up input configuration (e.g., input.config)

Refer to one of the sample input config files in [sample_input_config](https://github.com/NGWPC/nwm-cal-mgr/tree/nwm-cal-mgr/sample_input_config) to 
set up your configuration for calibration/validation.

2) run model setup workflow (nwm-msw-mgr) to produce input files
```bash
python -m mswm.manager build_calib input.config
```
3) run calibration
```bash
calibration [CALIB_CONFIG]
# or: python [NWM_ROOT]/nwm-cal-mgr/python/calibration.py [CALIB_CONFIG]
```
4) run validation
```bash
validation [VALID_CONTROL_CONFIG]
validation [VALID_BEST_CONFIG]
# or: python [NWM_ROOT]/nwm-cal-mgr/python/validation.py [CONFIG]
```
[VALID_CONTROL_CONFIG] and [VALID_BEST_CONFIG] are the config files for validation runs with the control/default
parameters and the best parameters, repectivly. These config files are produced at the end of calibration progress 
(see the log file for paths to these files).

5) run validation for an alternative iteration
```bash
validation_iteration [CALIB_COFIG] [woker ID] [iteration number]
# or: python [NWM_ROOT]/nwm-cal-mgr/python/validation_iteration.py [CALIB_COFIG] [woker ID] [iteration number]
```
