"""
This file reads input configuration file and creates the data and files files
for executing calibration and validation runs for difference NextGen formulations.

Example usage: python create_input.py input.config

@author: Xia Feng
"""

import argparse
import configparser
import copy
from datetime import timedelta
import os
import sys
import shutil
import time
import re
import geopandas as gpd
import pandas as pd

from createInput import ginputfunc as gfun

def create_input(filename):

    # define currently supported modules in each hydrologic process
    mod_all = {'SLOTH': ['sloth'],
                'snow': ['noah','snow17','ueb'],
                'ET': ['pet','noah'],
                'RR': ['cfe','cfe.xaj','topmodel','sac','lasam'],
                'routing': ['troute']}

    # define mapping for module names with spelling being different between GUI and ngen-cal 
    mod_dict = {
            'noah-owp-modular': 'noah',
            'snow-17': 'snow17',
            'cfe-s': 'cfe',
            'cfe-x': 'cfe.xaj',
            'sac-sma': 'sac',
            't-route': 'troute',
    }

    # Read input config file
    if not os.path.isfile(filename):
        raise ValueError(f'File {filename} does not exist')
    config  = configparser.ConfigParser()
    config.read(filename)
    
    if not {section: dict(config[section]) for section in config.sections()}:
        raise ValueError('Config file is empty')
    
    # convert inputs to dictionary
    configs = {}
    for sec in config.sections():
        configs[sec] = dict(config[sec])

    # reassign config sections for convenience
    conf1 = configs['General']
    conf2 = configs['Calibration']
    conf3 = configs['DataFile']

    # Time period 
    time_period={"run_time_period": {"calib": [conf2['calib_start_period'], conf2['calib_end_period']], 
                                    "valid": [conf2['valid_start_period'], conf2['valid_end_period']]}, 
                "evaluation_time_period": {"calib": [conf2['calib_eval_start_period'], conf2['calib_eval_end_period']],
                                            "valid": [conf2['valid_eval_start_period'], conf2['valid_eval_end_period']],
                                            "full": [conf2['full_eval_start_period'], conf2['full_eval_end_period']]}}

    # General settings 
    algorithm = conf2['optimization_algorithm']
    swarm_size = int(conf2['swarm_size'])
    strategy = {'type': 'estimation', 'algorithm': algorithm} 
    if algorithm == 'pso': 
        strategy.update({'parameters': {'pool': swarm_size, 'particles': swarm_size, \
            'options': {'c1': float(conf2['c1']), 'c2':float(conf2['c2']), 'w':float(conf2['w'])}}})
    if algorithm == 'gwo':
        strategy.update({'parameters': {'pool': swarm_size, 'particles': swarm_size}})
    general_cfg = {'strategy': strategy, 'name': conf1['run_type'], 'log': True, 'workdir': None, 'yaml_file': None,
                'start_iteration': int(conf2['start_iteration']), 'iterations': int(conf2['number_iteration']), \
                'restart': int(conf2['restart'])}

    # get list of modules
    if not conf1['models']:
        raise ValueError('Model must be specified')
    modules0 = [x.replace(" ", "") for x in re.split(',',conf1['models'])]
    modules = [mod_dict[m1.lower()] if m1.lower() in mod_dict.keys() else m1.lower() for m1 in modules0]
    
    # add sloth if CFE or LASAM is selected
    module_found = [x for x in ['cfe','cfe.xaj','lasam'] if x in modules]
    if len(module_found)==1 and 'sloth' not in modules:
        print("CFE or LASAM is used in the formulation. Add SLOTH to module list")
        modules = ['sloth'] + modules

    # make SMP and SFT are always selected together
    if 'smp' in modules and 'sft' not in modules:
        print('SMP and SFT must be selected together. Add SFT to module list')
        modules = modules + ['sft']
    if 'sft' in modules and 'smp' not in modules:
        print('SMP and SFT must be selected together. Add SMP to module list')
        modules = modules + ['smp']

    # always ensure troute is included
    if 'troute' not in modules:
        print("T-Route must be included in the formulation. Add T-Route to module list")
        modules = modules + ['troute']

    # rearrange modules in order of hydrologic processes
    modules1 = [m1 for p1 in mod_all.keys() for m1 in modules if m1 in mod_all[p1]]
    modules = []
    tmp = [modules.append(m1) for m1 in modules1 if m1 not in modules]

    # library files for all modules included in the formulation
    lib_file = {}
    modules1 = [m1 for m1 in modules if m1 != 'troute']
    for m1 in modules1:
        m2 = m1 if m1!='cfe.xaj' else 'cfe'
        lib_file[m1] = conf3[m2 + '_lib']  

    # Create Input directory 
    basin = conf1['basin']
    run_dir = os.path.join(conf1['main_dir'], '_'.join([conf2['objective_function'], conf2['optimization_algorithm']]))
    work_dir = os.path.join(run_dir, conf1['formulation'] + '/' + basin)
    input_dir = os.path.join(work_dir, 'Input/') 
    os.makedirs(input_dir, exist_ok=True)

    # Extract hydrofabric files
    gpkg_file = os.path.join(conf3['hydrofab_dir'], 'gauge_'+ basin +'.gpkg')
    catids = gpd.read_file(gpkg_file, layer='divides')['divide_id'].tolist()
    cat_file = os.path.join(input_dir, os.path.basename(gpkg_file)) 
    nexus_file = os.path.join(input_dir, os.path.basename(gpkg_file)) 
    walk_file = input_dir + '{}'.format(basin) + '_crosswalk.json'
    if not os.path.exists(cat_file):
        print(f'Creating symlink from {gpkg_file} to {cat_file}')
        os.symlink(gpkg_file, cat_file)
    gfun.create_walk_file(basin, gpkg_file, walk_file)    

    # Extract forcing files
    missing_catchment_files = []
    forcing_path = os.path.join(input_dir, 'forcing')
    os.makedirs(forcing_path, exist_ok=True)
    for catID in catids:
        ffile = os.path.join(conf3['forcing_dir'], catID + '.csv')
        # Make sure we have the file
        if not os.path.exists(ffile):
            print(f'Forcing file {ffile} does not exist')
            missing_catchment_files.append(ffile)
        else:
            target = os.path.join(forcing_path, os.path.basename(ffile))
            if not os.path.exists(target):
                #print(f'Creating symlink from {ffile} to {target}')
                os.symlink(ffile, target)
    if missing_catchment_files:
        raise ValueError(f'Missing catchment files in forcing data - {missing_catchment_files}')

    # Extract streamflow observation
    if conf3['obs_dir']:
        obs = pd.read_csv(os.path.join(conf3['obs_dir'], basin + '_hourly_discharge.csv'))[['dateTime','q_cms']]
        obs = obs.rename(columns={'dateTime': 'value_date', 'q_cms': 'obs_flow'})
        obsflow_file =  input_dir + '{}'.format(basin) + '_hourly_discharge.csv'
        obs.to_csv(obsflow_file, index=False)
    else:
        obsflow_file = None

    # loop through modules to create input files
    # always create CFE inputs first since sft/smp need data from CFE inputs if they are selected
    attr_file = conf3['attributes_file']
    run_configs = ['_troute_config_calib.yaml', '_troute_config_valid_control.yaml', '_troute_config_valid_best.yaml']
    modules1 = modules.copy()
    if 'cfe' in modules:
        modules1 =['cfe'] + [m1 for m1 in modules if m1!='cfe']
    if 'cfe.xaj' in modules:
        modules1 =['cfe.xaj'] + [m1 for m1 in modules if m1!='cfe.xaj']        
    for m1 in modules1:

        mod_input_dir = os.path.join(input_dir, m1 + '_input')

        if m1 in ['cfe', 'cfe.xaj']:
            gfun.create_cfe_input(catids, modules, attr_file, mod_input_dir)
        elif m1 == 'ueb':
            gfun.create_ueb_input(catids, time_period, attr_file, conf3['ueb_parameter_dir'],mod_input_dir) 
        elif m1 == 'snow17':
            gfun.create_snow17_input(catids, attr_file, mod_input_dir)
        elif m1 == "pet":
            gfun.create_pet_input(catids, attr_file, mod_input_dir)
        elif m1 == "sac":
            gfun.create_sac_input(catids, attr_file, mod_input_dir)
        elif m1 == 'noah':
            gfun.create_noah_input(catids, time_period, attr_file, conf3['noah_parameter_dir'], mod_input_dir)
        elif m1 == 'sft':
            sft_dir = os.path.join(input_dir, 'sft_input')
            smp_dir = os.path.join(input_dir, 'smp_input')
            cfe_dir = os.path.join(input_dir, 'cfe_input')
            if 'cfe.xaj' in modules:
                cfe_dir = os.path.join(input_dir, 'cfe.xaj_input')
            gfun.create_sft_smp_input(catids, modules, attr_file, cfe_dir, conf3['forcing_dir'], sft_dir, smp_dir)
        elif m1 == 'smp':
            continue
        elif m1 == 'lasam':
            gfun.create_lasam_input(catids, conf3['lasam_soil_parameter_file'], conf3['lasam_soil_class_file'], mod_input_dir)
        elif m1 == 'topmodel':
            os.makedirs(mod_input_dir, exist_ok=True)
            for catID in catids:
                run_file = os.path.join(conf3['topmd_dir'], '{}_topmodel'.format(catID) + '.run')
                params_file = os.path.join(conf3['topmd_dir'], '{}_topmodel_params'.format(catID) + '.dat')
                subcat_file = os.path.join(conf3['topmd_dir'], '{}_topmodel_subcat'.format(catID) + '.dat')

                gfun.change_topmodel_input(catID, run_file, params_file, subcat_file, mod_input_dir)

        elif m1 == 'troute':            
            for file_name, run_name in zip(run_configs, ['calib','valid','valid']): 
                routing_config_file = os.path.join(work_dir + '/Input', '{}'.format(basin) + file_name)
                if len(time_period['run_time_period'][run_name][0])!=0 & len(time_period['run_time_period'][run_name][0]):
                    run_range = pd.to_datetime(time_period['run_time_period'][run_name])
                    nts = len(pd.date_range(start=run_range[0], end=run_range[1], freq='5min'))-1
                    gfun.create_troute_config(gpkg_file, routing_config_file, time_period['run_time_period'][run_name][0], nts)

    # Create model realization file
    realization_file = work_dir + '/{}'.format(basin) + '_realization_config_bmi_calib.json' 
    routing_config_file = os.path.join(work_dir + '/Input', '{}'.format(basin) + run_configs[0])
    bmi_dir = {}
    modules1 = [m1 for m1 in modules if m1 not in ['sloth','troute']]
    for m1 in modules:
        bmi_dir[m1] = os.path.join(input_dir, m1 + '_input')
    rt_dict = {"routing": {"t_route_config_file_with_path": routing_config_file}} 
    gfun.create_realization_file(work_dir, lib_file, bmi_dir, forcing_path, realization_file, modules, time_period, rt_dict)

    # Create calibration configuration file 
    calib_config_file = os.path.join(work_dir + '/Input', '{}'.format(basin) + '_config_calib.yaml')
    model_dict = {'type': 'ngen', 'binary': conf3['ngen_exe_file'], 'realization': realization_file, 'catchments': cat_file, 'nexus': nexus_file,
            'crosswalk':  walk_file, 'obsflow': obsflow_file, 'nwmflow': conf3['nwmretro_file'],'strategy': 'uniform', 'params': None,
            'eval_params': {'objective': conf2['objective_function'], 
                            'evaluation_start': time_period['evaluation_time_period'][conf1['run_type']][0],
                            'evaluation_stop': time_period['evaluation_time_period'][conf1['run_type']][1], 
                            'valid_start_time': time_period['run_time_period']['valid'][0],
                            'valid_end_time': time_period['run_time_period']['valid'][1],
                            'valid_eval_start_time': time_period['evaluation_time_period']['valid'][0],
                            'valid_eval_end_time': time_period['evaluation_time_period']['valid'][1],
                            'full_eval_start_time': time_period['evaluation_time_period']['full'][0],
                            'full_eval_end_time': time_period['evaluation_time_period']['full'][1],
                            'save_output_iteration': int(conf2['save_output_iter']),
                            'save_plot_iteration': int(conf2['save_plot_iter']),
                            'save_plot_iter_freq': int(conf2['save_plot_iter_freq']),
                            'basinID': conf1['basin'], 
                            'threshold': float(conf2['streamflow_threshold']), 
                            'site_name': 'USGS ' + conf1['basin'] + ": " + conf2['station_name'],
                            'user': conf2['user_email']}} 
    general_dict = general_cfg.copy()
    general_dict['workdir'] = work_dir 
    general_dict['yaml_file'] = calib_config_file 
    gfun.create_calib_config_file(conf3['calib_parameter_file'], modules, work_dir, general_dict, model_dict, calib_config_file)
    print('Calibration yaml file generated at: ' + calib_config_file)


def main():
    # Create command line parser to supply input config file
    parser = argparse.ArgumentParser()
    parser.add_argument('input_config', type=str, help='input configuration file')
    args = parser.parse_args()

    try:
        create_input(args.input_config)
    except Exception as e:
        print(f"ERROR: uncaught exception: {e}")
        return 1
    return 0

if __name__ == "__main__":
   sys.exit(main())
