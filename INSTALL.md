# Installation instructions

Instructions on how to install, configure, and run calibration/validation are given below, 
where [VENV_ROOT] and [NWM_ROOT] refer to the directory to install python venv and nwm-cal-mgr
in your local workspace, respectively.

1. clone nwm-cal-mgr from Gitlab

```bash
cd [NWM_ROOT]
git clone -b development --recurse-submodules https://gitlab.sh.nextgenwaterprediction.com/NGWPC/nwm-ngen/ngen-cal.git
```

2. create python venv

```bash
cd [VENV_ROOT]
/usr/bin/python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
```
3. install package **calib**

```bash
cd [NWM_ROOT]/ngen-cal/python/calib
pip install . #or use "pip install -e ." to install the package as an editable 
```
4. install package **config**

```bash
cd [NWM_ROOT]/ngen-cal/python/config
pip install . #or use "pip install -e ." to install the package as an editable 
```

5. install dependency **mswm**

- clone mswm
```bash
cd [NWM_ROOT]
git clone -b development --recurse-submodules https://gitlab.sh.nextgenwaterprediction.com/NGWPC/nwm-ngen/mswm.git
```

- install mswm
```bash
cd [NWM_ROOT]/mswm
pip install .
```

### Usage

1) set up input configuration (e.g., input.config)

Refer to one of the sample input config files in [sample_input_config](sample_input_config) to 
set up your configuration for calibration/validation.

2) run model setup workflow (nwm-msw-mgr) to produce iput files
```bash
python -m mswm.manager build_default input.config
```
3) run calibration
```bash
python [NWM_ROOT]/ngen-cal/python/calibration.py [CALIB_CONFIG]
```