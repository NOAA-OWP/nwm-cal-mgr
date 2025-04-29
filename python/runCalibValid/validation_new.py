"""
This is main script to execute validation control run using the default model 
parameter set and validation best run using the best calibrated parameter set.

@author: Xia Feng
"""

import argparse
import logging
import os
from pathlib import Path
import subprocess
import shutil

import yaml
from ngen.cal.agent import Agent
from ngen.cal.configuration import General
from ngen.cal.validation_run import run_valid_ctrl_best

from ngen.cal.git_util import print_git_info_all


logger = logging.getLogger(__name__)

def main(general: General, model_conf):

    # Seed the random number generators if requested
    if( general.random_seed is not None):
        import random
        random.seed(general.random_seed)
        import numpy as np
        np.random.seed(general.random_seed)

    # Initialize agent
    agent = Agent(model_conf, general.valid_path, general, general.log, general.restart)

    # set environment variable for ngencerf backend
    os.environ['NGEN_RESULTS_DIR'] = str(Path(agent.workdir).parent.parent)
    logging.info(f'Set environment variable NGEN_RESULTS_DIR to: {os.environ["NGEN_RESULTS_DIR"]}')

    # read nwm retrospective streamflow if exists
    if agent.run_name != 'valid_control':
        if 'nwmflow' not in model_conf.keys() or model_conf['nwmflow'] is None:
            agent.nwmflow_file = ''
            logger.info('No NWM retrospective streamflow simulation is available for this location')
        else:
            agent.nwmflow_file = model_conf['nwmflow'] 
    
    # Execute validation control and best simulation
    if general.calibratable:
        logging.info("Running validation with calibratable model (control & best)")
        run_valid_ctrl_best(agent)
    else:
        logger.info('Running single validation (non-calibratable)')

        '''
        realization_src = Path(agent.model.realization)
        realization_dst = Path(agent.job.workdir) / realization_src.name

        if not realization_dst.exists():
            print(f"[DEBUG] Copying realization file {realization_src} -> {realization_dst}")
            shutil.copy(realization_src, realization_dst)

        # Update the agent's model realization path
        if hasattr(agent.model, "__root__"):
            agent.model.__root__.realization = realization_dst
        else:
            agent.model.realization = realization_dst

        # Rebuild the execution command with the updated realization path
        agent._model.model.args = '{} "all" {} "all" {}'.format(
            agent.model.catchments.resolve(),
            agent.model.nexus.resolve(),
            realization_dst.resolve()
        )
        '''
        # Now change into worker directory
        os.chdir(agent.job.workdir)

        print(f"[DEBUG] Current working directory: {os.getcwd()}")
        print(f"[DEBUG] Ngen execution command: {agent.cmd}")
        os.system(agent.cmd)

        '''
        # Split command into list form for subprocess
        command_list = agent.cmd.split()

        # Run ngen and capture output live
        with subprocess.Popen(command_list, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as proc:
            for line in proc.stdout:
                print(line, end='')  # Live print output
            proc.wait()
            if proc.returncode != 0:
                print(f"[ERROR] ngen failed with exit code {proc.returncode}")
            else:
                print("[SUCCESS] ngen executed successfully!")
                print(f"[DEBUG] Output generated in: {os.getcwd()}")
        '''
if __name__ == "__main__":
    print_git_info_all()

    # Create command line parser
    parser = argparse.ArgumentParser(description='Run Validation in NGEN architecture.')
    parser.add_argument('config_file', type=Path,
                        help='The configuration yaml file for catchments to be operated on')

    args = parser.parse_args()
    
    with open(args.config_file) as file:
        conf = yaml.safe_load(file)

    general = General(**conf['general'])

    model_conf = conf.get('model', {})
    if 'params' not in model_conf:
        model_conf['params'] = None

    # Change directory to workdir
    os.chdir(general.workdir)

    main(general, conf['model'])
