"""
This is the main script to read calibration configuration file and create inputs files needed for 
validation run with an alternative parameter set

@author: Yuqiong Liu
"""

import argparse
import os
from pathlib import Path
import pandas as pd
import yaml
import json
import shutil
from ngen.cal.agent import Agent
from ngen.cal.configuration import General
from ngen.cal.validation_run import run_valid_ctrl_best 

def main(general: General, model_conf, worker:str, iteration:int):

    # Initialize agent
    agent = Agent(model_conf, general.valid_path, general, general.log, general.restart)

    # read the parameter values from the *params_iteration.csv file
    file1 = Path(agent.calib_path,'ngen_'+worker+'_worker',conf['model']['eval_params']['basinID'] + '_params_iteration.csv')
    if not os.path.exists(file1):
        raise FileNotFoundError('File does not exist: ' + str(file1))
    df1 = pd.read_csv(file1).set_index('iteration')
    df1 = pd.DataFrame(df1.loc[iteration])   

    # write the realization and config files for validation run
    calibration_sets = agent.model.adjustables
    for calibration_set in calibration_sets:
        for calibration_object in calibration_set.adjustables:

            # get the alternative parameter values
            calibration_object.adf.loc[:,general.name] = df1[iteration].to_list()

            # create the realization file (with the alternative parameters) and the validation config file
            calibration_object.create_valid_realization_file(agent, calibration_object.adf, general.name) 

    # create t-route config file for the validation run
    configfl = os.path.join(agent.valid_path, os.path.basename(str(agent.realization_file)))
    valid_file = os.path.join(agent.valid_path, os.path.basename(configfl).replace("calib",general.name))
    if not os.path.exists(valid_file):
        raise FileNotFoundError('File does not exist: ' + str(valid_file))
    with open(valid_file) as fp:
        data = json.load(fp)

    troute_config = data['routing']['t_route_config_file_with_path']
    troute_config_best = troute_config.replace(general.name, 'valid_best')
    if not os.path.exists(troute_config_best):
        raise FileNotFoundError('File does not exist: ' + str(troute_config_best))
    shutil.copy(troute_config_best, troute_config)

    # read validation config file
    config_file_valid = os.path.join(agent.valid_path, os.path.basename(agent.yaml_file).replace('calib', general.name))
    if not os.path.exists(config_file_valid):
        raise FileNotFoundError('File does not exist: ' + str(config_file_valid))    
    with open(config_file_valid) as file:
        conf_valid = yaml.safe_load(file)
    general_valid = General(**conf_valid['general'])

    # Change directory to workdir
    os.chdir(general_valid.workdir)

    print("Starting Validation Run")

    # Initialize agent
    agent_valid = Agent(conf_valid['model'], general_valid.valid_path, general_valid, general_valid.log, general_valid.restart)
    
    # Execcute validation simulation
    run_valid_ctrl_best(agent_valid)

    print("Validation completed")

if __name__ == "__main__":

    # Create the command line parser
    parser = argparse.ArgumentParser(description='Create validation inputs based on calibration config file')
    parser.add_argument('config_file', type=Path,help='The configuration yaml file for calibration')
    parser.add_argument('worker_id', type=str,help='Worked ID as identified by the random string created during calibration')
    parser.add_argument('iter_no', type=int, help='Iternation number')

    args = parser.parse_args()
    
    with open(args.config_file) as file:
        conf = yaml.safe_load(file)
    
    general = General(**conf['general'])
    general.name = 'valid_' + args.worker_id + '_iter' + str(args.iter_no)

    main(general, conf['model'], args.worker_id, args.iter_no)
