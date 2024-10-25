"""
This is the main script to read calibration configuration file and execute calibration run. 

@author: Nels Frazer and Xia Feng
"""

import argparse
from os import chdir
from pathlib import Path

import yaml

from ngen.cal.agent import Agent
from ngen.cal.configuration import General
from ngen.cal.search import dds, dds_set, pso_search, gwo_search
from ngen.cal.strategy import Algorithm

import sys  
import logging 
from datetime import datetime, timezone
import os
import time

LOG = logging.getLogger(__name__)

def create_timestamp() -> str: 
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    

def log_level_set():
    '''
    Set logging level and specify logger configuration.
    
    Arguments
    ---------
    input_parameters (dict): User input logging parameters
    
    Returns
    -------
    None
    
    Notes
    -----
    In the absense of user-specified logging level, level defaults to DEBUG
    See also https://docs.python.org/3/library/logging.html
    
    '''

    log_level = 'DEBUG'
    if True:
        log_file_dir = f"/ngencerf/data/run-logs/ngen_cal_{create_timestamp()}/"
        log_file_name = "ngen_cal_log.txt"
        os.makedirs(log_file_dir, exist_ok=True)
        logFilePath = os.path.join(log_file_dir, log_file_name)
        try:
            logFile = open(logFilePath, "a")
            print(f"Logging into: {logFilePath}")
        except IOError:
            print(f"Can't Open local directory Log File: {logFilePath}", file=sys.stderr)
        
        logging.Formatter.converter = time.gmtime
        logging.basicConfig(
            force=True,
            level=log_level,
            format='%(asctime)s.%(msecs)03d NGEN_CAL %(levelname)s    %(message)s',
            datefmt='%Y-%m-%dT%H:%M:%S',
            handlers=[
            logging.FileHandler(logFilePath, mode='a'),  # Log to a file
            logging.StreamHandler(sys.stdout)  
        ])
    else:       
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)s - %(funcName)s]: %(message)s',
            stream=sys.stderr,
        )  

    LOG.info("Inside log_level_set") 
    
def main(general: General, model_conf):

    # Seed the random number generators if requested
    if( general.random_seed is not None):
        import random
        random.seed(general.random_seed)
        import numpy as np
        np.random.seed(general.random_seed)

    # setup logging
    log_level_set()

    LOG.info("Starting calib")

    """
    TODO calibrate each "catcment" independely, but there may be something interesting in grouping various formulation params
    into a single variable vector and calibrating a set of heterogenous formultions...
    """
    start_iteration = 0

    # Initialize the starting agent
    agent = Agent(model_conf, general.calib_path, general, general.log, general.restart)
    if general.strategy.algorithm == Algorithm.dds:
        start_iteration = general.start_iteration
        if general.restart:
            start_iteration = agent.restart()
        func = dds_set #FIXME what about explicit/dds
    elif general.strategy.algorithm == Algorithm.pso: #TODO how to restart PSO?
        if agent.model.strategy != "uniform":
            LOG.info("Can only use PSO with the uniform model strategy")
            return
        if general.restart:
            LOG.info("Restart not supported for PSO search, starting at 0")
        func = pso_search
    elif general.strategy.algorithm == Algorithm.gwo: 
        if agent.model.strategy != "uniform":
            LOG.info("Can only use GWO with the uniform model strategy")
            return
        if general.restart:
            start_iteration = agent.restart()
        func = gwo_search

    LOG.info("Starting Iteration: {}".format(start_iteration))
    LOG.info("Starting calibration loop")
    if general.strategy.algorithm in [Algorithm.pso, Algorithm.gwo]:
        LOG.info(f"Note the full set of plots are only produced for the first worker at: {agent.job.workdir}")
              
    # NOTE this assumes we calibrate each catchment independently, it may be possible to design an "aggregate" calibration
    # that works in a more sophisticated manner.
    if agent.model.strategy == 'explicit': #FIXME this needs a refactor...should be able to use a calibration_set with explicit loading
        for catchment in agent.model.adjustables:
            dds(start_iteration, general.iterations, catchment, agent)

    elif agent.model.strategy == 'independent':
        #for catchment_set in agent.model.adjustables:
        func(start_iteration, general.iterations, agent)

    elif agent.model.strategy == 'uniform':
        func(start_iteration, general.iterations, agent)


if __name__ == "__main__":

    # Create the command line parser
    parser = argparse.ArgumentParser(description='Calibrate catchments in NGEN architecture.')
    parser.add_argument('config_file', type=Path,
                        help='The configuration yaml file for catchments to be operated on')

    args = parser.parse_args()
    
    with open(args.config_file) as file:
        conf = yaml.safe_load(file)

    general = General(**conf['general'])

    # Change directory to workdir
    chdir(general.workdir)

    main(general, conf['model'])
