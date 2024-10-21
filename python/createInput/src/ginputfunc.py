""" 
This module contains a variety of functions to create different input files. 

@author: Xia Feng
"""

import copy
import datetime
import glob
import json
import os
import re
import sys
import shutil
import subprocess
import fnmatch
from fileinput import FileInput
from functools import partial
from typing import List, Union, Dict
from pathlib import Path
import geopandas as gpd
import pandas as pd
import yaml
import logging
logger = logging.getLogger(__name__)

from tempfile import mkstemp
from createInput import settings

def replace_path(source_file_path, par_path, data_type_codes):
    fh, target_file_path = mkstemp()
    with open(target_file_path, 'w') as target_file:
       with open(source_file_path, 'r') as source_file:
         data = source_file.readlines() 
         for i in range(2, len(data), 3):
            if data[ i ][:1] in data_type_codes:
                if data[ i + 1 ][:1] != '/':
                    data[ i + 1 ] = par_path + '/' + data[ i + 1 ] 
                      
         target_file.writelines(data) 

    os.remove(source_file_path)
    shutil.move(target_file_path, source_file_path)


__all__ = [
           'create_walk_file',
           'create_cfe_input',
           'create_noah_input',
           'create_sft_smp_input',
           'create_lasam_input',
           'create_snow17_input',
           'create_ueb_input',
           'create_sac_input',
           'create_pet_input',
           'change_topmodel_input',
           'create_troute_config',
           'create_realization_file',
           'create_calib_config_file',
          ]


def create_walk_file(
    gageID: str, 
    gpkg_file: Union[str, Path], 
    walk_file: Union[str, Path],
)->None:

    """ Create crosswalk file

    Parameters
    ----------
    gageID : stream gage ID at the outlet of basin
    gpkg_file : hydrofabric GeoPackage file
    walk_file : crosswalk file

    Returns 
    ----------
    None

    """

    df_cat = gpd.read_file(gpkg_file, layer='divides')
    df_cat.set_index('divide_id', inplace=True)
    df_nexus = gpd.read_file(gpkg_file, layer='nexus')
    df_nexus.set_index('id', inplace=True)
    df_flowpaths = gpd.read_file(gpkg_file, layer='flowpaths')
    df_flowpaths = df_flowpaths.sort_values('hydroseq')
    df_flowpaths.set_index('toid', inplace=True)

    gageid = []
    cw = {}
    for x in df_cat.index:
        hu = df_nexus.loc[df_cat.loc[x, 'toid'], 'hl_uri']
        if hu == 'NA' or not hu.startswith('Gages'): 
            catcw = {x: {"Gage_no": ""}}
        elif hu.startswith('Gages'):  
            if len(hu.split(','))>1 and gageID in hu:   
                gage=gageID
            else:
                gage = hu.split('-')[1]
            gageid.append(gage) 
            if gage == gageID:
                subdf = df_flowpaths.loc[[df_cat.loc[x, 'toid']]]
                if subdf.shape[0] == 1:
                    catcw = {x: {"Gage_no": gage}}
                else: 
                    # Select nearest one among multiple catchments draining to the gage 
                    if subdf['id'][-1].replace('wb','cat') == x:
                         print(x)
                         catcw = {x: {"Gage_no": gage}}
                    else:
                         catcw = {x: {"Gage_no": ""}}
            else:
                catcw = {x: {"Gage_no": ""}}
        cw.update(catcw)
    if len(set(gageid))>1:    
        print('more than 1 gage found, please check')
    with open(walk_file, 'w') as outfile:
        json.dump(cw, outfile, indent=4, separators=(", ", ": "), sort_keys=False)


def create_cfe_input(
    catids: List[str],  
    modules: List[str],
    attr_file: Union[str, Path],
    cfe_input_dir: Union[str, Path],
)->None:

    """ Create BMI initial configuration file for CFE with Schaake or Xianjiang infiltration and runoff scheme

    Parameters
    ----------
    catids : catchment IDs in the basin
    modules: list of modules in the formulation
    attr_file : file containing model parameter attributes
    cfe_input_dir: directory to save configuration files

    Returns
    ----------
    None

    Note
    ----------
    User needs to compute GIUH using other software like R whitebox package following the example 
    https://github.com/NOAA-OWP/SoilMoistureProfiles/blob/ajk/basin_workflow/basin_workflow/giuh_twi/giuh.R
    and replace the fixed GIUH assigned in this code with the calculated value.  

    """

    os.makedirs(cfe_input_dir, exist_ok=True)

    # Read hydrofabric attribute file
    dfa = pd.read_parquet(attr_file)
    dfa.set_index("divide_id", inplace=True)
 
     # surface partitioning scheme
    scheme = 'Schaake'
    if ('cfex' in modules):
        scheme = 'Xinanjiang'

    # Create bmi config files
    for catID in catids:
        cfe_bmi_file = os.path.join(cfe_input_dir, catID + "_bmi_config_cfe.txt")
        f = open(cfe_bmi_file, "w")
        f.write("%s" %("forcing_file=BMI\n"))
        f.write("%s" %("surface_partitioning_scheme=" + scheme +"\n"))
        f.write("%s" %("soil_params.depth=2.0[m]\n"))
        f.write("%s" %("soil_params.b=" + str(dfa.loc[catID]['bexp_soil_layers_stag=1']) + "[]\n"))
        f.write("%s" %("soil_params.satdk=" + str(dfa.loc[catID]['dksat_soil_layers_stag=1']) + "[m s-1]\n"))
        f.write("%s" %("soil_params.satpsi=" + str(dfa.loc[catID]['psisat_soil_layers_stag=1']) + "[m]\n"))
        f.write("%s" %("soil_params.slop=" + str(dfa.loc[catID]['slope']) + "[m/m]\n"))
        f.write("%s" %("soil_params.smcmax=" + str(dfa.loc[catID]['smcmax_soil_layers_stag=1']) + "[m/m]\n"))
        f.write("%s" %("soil_params.wltsmc=" + str(dfa.loc[catID]['smcwlt_soil_layers_stag=1']) + "[m/m]\n"))
        f.write("%s" %("soil_params.expon=1.0[]\n"))
        f.write("%s" %("soil_params.expon_secondary=1.0[]\n"))
        f.write("%s" %("refkdt=" + str(dfa.loc[catID]['refkdt']) + "\n"))
        f.write("%s" %("max_gw_storage=" + str(dfa.loc[catID]['gw_Zmax']/1000.) + "[m]\n"))
        f.write("%s" %("Cgw=" + str(dfa.loc[catID]['gw_Coeff']*3600*1e-6) + "[m h-1]\n"))
        f.write("%s" %("expon=" + str(dfa.loc[catID]['gw_Expon']) + "[]\n"))
        f.write("%s" %("gw_storage=0.05[m/m]\n"))
        f.write("%s" %("alpha_fc=0.33\n"))
        f.write("%s" %("soil_storage=0.05[m/m]\n"))
        f.write("%s" %("K_nash=0.03[]\n"))
        f.write("%s" %("K_lf=0.01[]\n"))
        f.write("%s" %("nash_storage=0.0,0.0\n"))
        f.write("%s" %("num_timesteps=1\n"))
        f.write("%s" %("verbosity=1\n"))
        f.write("%s" %("DEBUG=0\n"))
        f.write("%s" %("giuh_ordinates=0.55,0.25,0.2\n"))
        f.write("%s" %("surface_runoff_scheme=GIUH\n"))

        if 'sft' in modules:
            f.write("%s" %("sft_coupled=true\n"))
            f.write("%s" %("ice_content_threshold=0.3\n"))

        # add the new parameters for cfex
        # TODO: read these catchment-specific parameters from the NWMv3 model attributes parquet file
        # The current parquet file we have access to was likely based on NWMv2.1 and hence missing these XAJ parameters
        f.write("%s" %("a_Xinanjiang_inflection_point_parameter=-0.212938\n"))
        f.write("%s" %("b_Xinanjiang_shape_parameter=0.666238\n"))
        f.write("%s" %("x_Xinanjiang_shape_parameter=0.02414\n"))
        f.write("%s" %("urban_decimal_fraction=0.0\n"))

        f.close()


def create_noah_input(
    catids: List[str],
    time_period: dict,
    attr_file: Union[str, Path],
    param_dir_source: Union[str, Path],
    noah_input_dir: Union[str, Path],
)->None:

    """ Create BMI configuration file for Noah-OWP-Modular

    Parameters
    ----------
    catids : catchment IDs in the basin
    time_period : simulation and evaluation time period
    param_dir_source : source directory containing Noah-OWP-Modular parameter files
    noah_input_dir: directory to save configuration files

    Returns
    ----------
    None

    """

    # Create symlink for parameter directory
    os.makedirs(noah_input_dir, exist_ok=True)
    noah_par_tables = ['SOILPARM.TBL','MPTABLE.TBL','GENPARM.TBL']
    for par in noah_par_tables:
        src = os.path.join(param_dir_source,par)
        dst = os.path.join(noah_input_dir,par)
        with open(src) as f:
            if not os.path.exists(dst):
                os.symlink(src, dst)

    # Read hydrofabric attribute file
    dfa = pd.read_parquet(attr_file)
    dfa.set_index("divide_id", inplace=True)

    # Files for the calibration and validation run
    for run_name in ['calib','valid']:
        if time_period['run_time_period'][run_name][0] and time_period['run_time_period'][run_name][1]:
            # Date
            startdate = time_period['run_time_period'][run_name][0]
            startdate = datetime.datetime.strptime(startdate, "%Y-%m-%d %H:%M:%S") + datetime.timedelta(hours=1)
            startdate = startdate.strftime("%Y%m%d%H%M")
            enddate = datetime.datetime.strptime(time_period['run_time_period'][run_name][1], "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d%H%M")

            # Specify options for namelist file
            for catID in catids:
                tslp = dfa.loc[catID]['slope_mean']
                azimuth = dfa.loc[catID]['aspect_c_mean']
                lat = dfa.loc[catID]['Y']
                lon = dfa.loc[catID]['X']
                isltype = dfa.loc[catID]["ISLTYP"]
                vegtype = dfa.loc[catID]["IVGTYP"]
                sfctype = 2 if vegtype ==16 else 1 
                nom_lst = ['&timing',
                           "  " + "dt".ljust(19) +  "= 3600.0" + "                       ! timestep [seconds]",
                           "  " + "startdate".ljust(19) + "= " + "'" + startdate + "'" + "               ! UTC time start of simulation (YYYYMMDDhhmm)",
                           "  " + "enddate".ljust(19) + "= " + "'" + enddate + "'" + "               ! UTC time end of simulation (YYYYMMDDhhmm)",
                           "  " + "forcing_filename".ljust(19) + "= '.'" + "                          ! file containing forcing data",
                           "  " + "output_filename".ljust(19) + "= '.'",
                           '/',
                           "",
                           '&parameters',
                           "  " + "parameter_dir".ljust(19) + "= " + "'" + noah_input_dir + "'",
                           "  " + "general_table".ljust(19) + "= 'GENPARM.TBL'" + "                ! general param tables and misc params",
                           "  " + "soil_table".ljust(19) + "= 'SOILPARM.TBL'" + "               ! soil param table",
                           "  " + "noahowp_table".ljust(19) + "= 'MPTABLE.TBL'" + "                ! model param tables (includes veg)",
                           "  " + "soil_class_name".ljust(19) + "= 'STAS'" + "                       ! soil class data source - 'STAS' or 'STAS-RUC'",
                           "  " + "veg_class_name".ljust(19) + "= 'USGS'" + "                       ! vegetation class data source - 'MODIFIED_IGBP_MODIS_NOAH' or 'USGS'",
                           '/',
                           "",
                           '&location',
                           "  " + "lat".ljust(19) + "= " + str(lat) + "            ! latitude [degrees]  (-90 to 90)",
                           "  " + "lon".ljust(19) + "= " + str(lon) + "           ! longitude [degrees] (-180 to 180)",
                           "  " + "terrain_slope".ljust(19) + "= " + str(tslp) + "           ! terrain slope [degrees]",
                           "  " + "azimuth".ljust(19) + "= " + str(azimuth) + "           ! terrain azimuth or aspect [degrees clockwise from north]",
                           '/',
                           "",
                           "&forcing",
                           "  " + "ZREF".ljust(19) + "= 10.0" + "                         ! measurement height for wind speed (m)",
                           "  " + "rain_snow_thresh".ljust(19) + "= 0.5" + "                          ! rain-snow temperature threshold (degrees Celcius)",
                           "/",
                           "",
                           "&model_options",
                           "  " + "precip_phase_option".ljust(34) + "= 6",
                           "  " + "snow_albedo_option".ljust(34) + "= 1",
                           "  " + "dynamic_veg_option".ljust(34) + "= 4",
                           "  " + "runoff_option".ljust(34) + "= 3",
                           "  " + "drainage_option".ljust(34) + "= 8",
                           "  " + "frozen_soil_option".ljust(34) + "= 1",
                           "  " + "dynamic_vic_option".ljust(34) + "= 1",
                           "  " + "radiative_transfer_option".ljust(34) + "= 3",
                           "  " + "sfc_drag_coeff_option".ljust(34) + "= 1",
                           "  " + "canopy_stom_resist_option".ljust(34) + "= 1",
                           "  " + "crop_model_option".ljust(34) + "= 0",
                           "  " + "snowsoil_temp_time_option".ljust(34) + "= 3",
                           "  " + "soil_temp_boundary_option".ljust(34) + "= 2",
                           "  " + "supercooled_water_option".ljust(34) + "= 1",
                           "  " + "stomatal_resistance_option".ljust(34) + "= 1",
                           "  " + "evap_srfc_resistance_option".ljust(34) + "= 4",
                           "  " + "subsurface_option".ljust(34) + "= 2",
                           "/",
                           "",
                           "&structure",
                           "  " + "isltyp".ljust(17) + "= " + str(isltype) + "              ! soil texture class",
                           "  " + "nsoil".ljust(17) + "= 4              ! number of soil levels",
                           "  " + "nsnow".ljust(17) + "= 3              ! number of snow levels",
                           "  " + "nveg".ljust(17) + "= 27             ! number of vegetation type",
                           "  " + "vegtyp".ljust(17) + "= " + str(vegtype) + "             ! vegetation type",
                           "  " + "croptype".ljust(17) + "= 0              ! crop type (0 = no crops; this option is currently inactive)",
                           "  " + "sfctyp".ljust(17) + "= " + str(sfctype) + "              ! land surface type, 1:soil, 2:lake",
                           "  " + "soilcolor".ljust(17) + "= 4              ! soil color code",
                           "/",
                           "",
                           "&initial_values",
                           "  " + "dzsnso".ljust(10) + "= 0.0, 0.0, 0.0, 0.1, 0.3, 0.6, 1.0      ! level thickness [m]",
                           "  " + "sice".ljust(10) + "= 0.0, 0.0, 0.0, 0.0                     ! initial soil ice profile [m3/m3]",
                           "  " + "sh2o".ljust(10) + "= 0.3, 0.3, 0.3, 0.3                     ! initial soil liquid profile [m3/m3]",
                           "  " + "zwt".ljust(10) + "= -2.0                                   ! initial water table depth below surface [m]",
                           "/",
                           ]
               
                namelst = os.path.join(noah_input_dir, '{}'.format(catID) + '_' + run_name + '.input')
                with open(namelst, 'w') as outfile:
                    outfile.writelines('\n'.join(nom_lst))
                    outfile.write("\n")


def create_sft_smp_input(
    catids: List[str],  
    modules: List[str], 
    attr_file: Union[str, Path],
    cfe_dir: Union[str, Path],
    forcing_dir: Union[str, Path], 
    sft_dir: Union[str, Path], 
    smp_dir: Union[str, Path], 
)->None:

    """ Create BMI configuration file for soil freeze and thaw module, and soil moisture profiles

    Parameters
    ----------
    catids : catchment IDs in the basin
    modules: list of modules in the formulation 
    attr_file : file containing model parameter attributes
    cfe_dir : directory containing cfe bmi configuration files 
    forcing_dir : directory containing forcing files 
    sft_dir : directory for writing sft bmi configuration files 
    smp_dir : directory for writing smp bmi configuration files

    Returns 
    ----------
    None

    """

    os.makedirs(sft_dir, exist_ok=True)
    os.makedirs(smp_dir, exist_ok=True)

    # Read attribute file to obtain quartz
    dfa = pd.read_parquet(attr_file)
    dfa.set_index('divide_id', inplace=True)

    # Ice fraction scheme
    icefscheme = 'Schaake'
    if ('cfex' in modules):
        icefscheme = 'Xinanjiang'

    # Create bmi config files
    for catID in catids:

        # Read cfe BMI files
        cfe_bmi_file = os.path.join(cfe_dir, fnmatch.filter(os.listdir(cfe_dir), '*'+catID+'*.txt')[0])
        df = pd.read_table(cfe_bmi_file,  delimiter='=', names=["Params","Values"], index_col=0)

        # Obtain annual mean surface temperature as proxy for initial soil temperature
        fdf = pd.read_table(os.path.join(forcing_dir, catID + '.csv'),  delimiter=',')
        mtemp = round(fdf['T2D'].mean(), 2)

        # Create sft list
        sft_lst = ['verbosity=none', 'soil_moisture_bmi=1', 'end_time=1.[d]', 'dt=1.0[h]', 
                   'soil_params.smcmax=' + df.loc['soil_params.smcmax'].iloc[0], 
                   'soil_params.b=' + df.loc['soil_params.b'].iloc[0], 
                   'soil_params.satpsi=' + df.loc['soil_params.satpsi'].iloc[0], 
                   'soil_params.quartz=' + str(dfa.loc[catID][[x for x in dfa.columns.to_list() if 'quartz' in x]].mean()) +'[]', 
                   'ice_fraction_scheme=' + icefscheme, 
                   'soil_z=0.1,0.3,1.0,2.0[m]',
                   'soil_temperature=' + ','.join([str(mtemp)]*4) + '[K]',
                  ]
        sft_bmi_file = os.path.join(sft_dir, catID + '_bmi_config_sft.txt')
        with open(sft_bmi_file, "w") as f:
            f.writelines('\n'.join(sft_lst))

        # Create smp list
        smp_lst = ['verbosity=none', 
               'soil_params.smcmax=' + df.loc['soil_params.smcmax'].iloc[0], 
               'soil_params.b=' + df.loc['soil_params.b'].iloc[0], 
               'soil_params.satpsi=' + df.loc['soil_params.satpsi'].iloc[0], 
               'soil_z=0.1,0.3,1.0,2.0[m]']
        if 'cfes' in modules or 'cfex' in modules:
            smp_lst += ['soil_storage_model=conceptual', 'soil_storage_depth=2.0']
        elif 'lasam' in modules:
            smp_lst += ['soil_storage_model=layered', 'soil_moisture_profile_option=constant', 'soil_depth_layers=2.0', 'water_table_depth=10[m]']
        smp_bmi_file = os.path.join(smp_dir, catID + '_bmi_config_smp.txt')
        with open(smp_bmi_file, "w") as f:
            f.writelines('\n'.join(smp_lst))


def create_snow17_input(
    catids: List[str],
    attr_file: Union[str, Path],
    snow17_input_dir: str
)->None:

    """ Create BMI configuration file for Snow17

    Parameters
    ----------
    catids : catchment IDs in the basin
    cfe_bmi_dir : directory for the cfe bmi configuration file
    snow17_param_file : soil hydraulic parameter file
    snow17_bmi_dir : directory for the lasam bmi configuration file

    Returns
    ----------
    None

   """
    os.makedirs(snow17_input_dir, exist_ok=True)

    # Read hydrofabric attribute file
    dfa = pd.read_parquet(attr_file)
    dfa.set_index("divide_id", inplace=True)

    param_list = ['hru_id HHWM8IL HHWM8IU',
            'hru_area 2994.7 1271.3',
            'latitude 47.78 47.78',
            'elev 1612.50 2153.35',
            'scf 2.15177 1.86124',
            'mfmax 0.930472 0.754924',
            'mfmin 0.137 0.160',
            'uadj 0.003103 0.208042',
            'si 1515.00 1515.00',
            'pxtemp 0.713424 0.220934',
            'nmf 0.150 0.150',
            'tipm 0.200 0.050',
            'mbase 0.000 0.000',
            'plwhc 0.030 0.030',
            'daygm 0.300 0.200',
            'adc1 0.050 0.050',
            'adc2 0.090 0.090',
            'adc3 0.160 0.160',
            'adc4 0.310 0.310',
            'adc5 0.540 0.540',
            'adc6 0.740 0.740',
            'adc7 0.840 0.840',
            'adc8 0.890 0.890',
            'adc9 0.930 0.930',
            'adc10 0.970 0.970',
            'adc11 1.000 1.000']

    for catID in catids:
        input_file = os.path.join(snow17_input_dir, 'snow17-init-' +catID + '.namelist.input')
        param_file = os.path.join(snow17_input_dir, 'snow17_params-' +catID + '.HHWM8.txt')

        with open(param_file, "w") as f:
            f.writelines('\n'.join(param_list))

        input_list = ['&SNOW17_CONTROL',
                '! === run control file for snow17bmi v. 1.x ===',
                '',
                '! -- basin config and path information',
                'main_id             = "' + catID + '"     ! basin label or gage id',
                'n_hrus              = 1            ! number of sub-areas in model',
                'forcing_root        = "extern/snow17/test_cases/ex1/input/forcing/forcing.snow17bmi."',
                'output_root         = "data/output/output.snow17bmi."',
                'snow17_param_file   = "' + param_file + '"',
                'output_hrus         = 1            ! output HRU results? (1=yes; 0=no)',
                '',
                '! -- run period information',
                'start_datehr        = 2017120101   ! start date time, backward looking (check)',
                'end_datehr          = 2017120123   ! end date time',
                'model_timestep      = 3600        ! in seconds (86400 seconds = 1 day)',
                '',
                '! -- state start/write flags and files',
                'warm_start_run      = 0  ! is this run started from a state file?  (no=0 yes=1)',
                "write_states        = 0  ! write restart/state files for 'warm_start' runs (no=0 yes=1)",
                '',
                '! -- filenames only needed if warm_start_run = 1',
                'snow_state_in_root  = "data/state/snow17_states."  ! input state filename root',
                '',
                '! -- filenames only needed if write_states = 1',
                'snow_state_out_root = "data/state/snow17_states."  ! output states filename root',
                '/',
                ''
                ]
        with open(input_file, "w") as f:
            f.writelines('\n'.join(input_list))

def create_ueb_input(
    catids: List[str],
    time_period: dict,
    attr_file: Union[str, Path],
    param_dir_source: Union[str, Path],
    ueb_input_dir: str
)->None:

    """ Create BMI configuration file for ueb

    Parameters
    ----------
    catids : catchment IDs in the basin
    time_period: simulation time period
    attr_file : attributes file containing info on lat/lon/slope/aspect etc
    param_dir_source : directory containing UEB parameter files
    ueb_input_dir : directory for the UEB bmi configuration file

    Returns
    ----------
    None

   """
    os.makedirs(ueb_input_dir, exist_ok=True)

    # Read hydrofabric attribute file
    dfa = pd.read_parquet(attr_file)
    dfa.set_index("divide_id", inplace=True)

    param_list = [
               'Model Parameters',
               'irad:  Radiation control flag (0=from ta, 1= input qsi, 2= input qsi,qli 3= input qnet)',
               '2',
               'ireadalb:  Albedo reading control flag (0=albedo is computed internally, 1 albedo is read)',
               '0',
               'tr: Temperature above which all is rain (3 C)',
               '3   ',
               'ts: Temperature below which all is snow (-1 C)',
               '-1        ',
               'ems: Emissivity of snow (nominally 0.99)',
               '0.98  ',
               'cg:  Ground heat capacity (nominally 2.09 KJ/kg/C)',
               '2.09          ',
               'z: Nominal meas. heights for air temp. and humidity (2m)',
               '2 ',
               'zo:  Surface aerodynamic roughness (m)',
               '0.010     ',
               'rho: Snow Density (Nominally 450 kg/m^3)',
               '337 ',
               'rhog:  Soil Density (nominally 1700 kg/m^3)',
               '1700 ',
               'lc: Liquid holding capacity of snow (0.05)',
               '0.05     ',
               'ks:  Snow Saturated hydraulic conductivity (20 m/hr)',
               '20',
               'de:  Thermally active depth of soil (0.1 m)',
               '0.1   ',
               'avo:  Visual new snow albedo (0.95)',
               '0.85 ',
               'anir0: NIR new snow albedo (0.65)',
               '0.65 ',
               'lans: The thermal conductivity of fresh (dry) snow (W/m-K)',
               '0.278   ',
               'lang: the thermal conductivity of soil (W/m-K)',
               '1.11  ',
               'wlf:  Low frequency fluctuation in deep snow/soil layer ',
               '0.0654      ',
               'rd1: Amplitude correction coefficient of heat conduction (1)',
               '1 ',
               'dnews:  The threshold depth of for new snow (0.001 m)',
               '0.001  ',
               'emc:   Emissivity of canopy',
               '0.98   ',
               'alpha: Scattering coefficient for solar radiation',
               '0.5   ',
               'alphal:   Scattering coefficient for long wave radiation',
               '0.0  ',
               'g: leaf orientation with respect to zenith angle',
               '0.5   ',
               'uc:  Unloading rate coefficient (Per hour) (Hedstrom and Pomeroy, 1998)',
               '0.004626286  ',
               'as:  Fraction of extraterrestrial radiation on cloudy day, Shuttleworth (1993)  ',
               '0.25   ',
               'Bs:     (as+bs):Fraction of extraterrestrial radiation on clear day, Shuttleworth ',
               '0.5      ',
               'lambda: Ratio of direct atm radiation to diffuse, worked out from Dingman ',
               '0.857143 ',
               'rimax:  Maximum value of Richardson number for stability correction',
               '0.16',
               'wcoeff: Wind decay coefficient for the forest',
               '0.5     ',
               'a: A in Bristow-Campbell formula for atmospheric transmittance',
               '0.8      ',
               'c: C in Bristow-Campbell formula for atmospheric transmittance',
               '2.4 '
    ]

    # Files for the calibration and validation run
    for run_name in ['calib','valid']:
        if time_period['run_time_period'][run_name][0] and time_period['run_time_period'][run_name][1]:
            # Date
            startdate = time_period['run_time_period'][run_name][0]
            startdate = datetime.datetime.strptime(startdate, "%Y-%m-%d %H:%M:%S") + datetime.timedelta(hours=1)
            startdate = startdate.strftime("%Y%m%d%H%M")
            enddate = datetime.datetime.strptime(time_period['run_time_period'][run_name][1], "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d%H%M")
            for catID in catids:
                tslp = dfa.loc[catID]['slope_mean']
                azimuth = dfa.loc[catID]['aspect_c_mean']
                lat = dfa.loc[catID]['Y']
                lon = dfa.loc[catID]['X']
                input_file = os.path.join(ueb_input_dir, 'ueb-init-' +catID + '_' + run_name + '.dat')
                param_file = os.path.join(ueb_input_dir, 'ueb_params-' +catID +'_' + run_name +  '.dat')
                site_file = os.path.join(ueb_input_dir, 'ueb_sitevars-' +catID + '_' + run_name + '.dat')
                inputctr_file = os.path.join(ueb_input_dir, 'ueb_inputctr-' +catID +'_' + run_name +  '.dat')
                outputctr_file = os.path.join(ueb_input_dir, 'ueb_outputctr-' +catID +'_' + run_name +  '.dat')

                with open(param_file, "w") as f:
                    f.writelines('\n'.join(param_list))

                site_var_list = [
                'Site and Initial Condition Input Variables',
                'USic:  Energy content initial condition (kg m-3)',
                '0',
                '0.0',
                'WSis:  Snow water equivalent initial condition (m)',
                '0',
                '0.0',
                'Tic:  Snow surface dimensionless age initial condition ',
                '0',
                '0.0',
                'WCic:  Snow water equivalent of canopy conditio(m) ',
                '0',
                '0.0',
                'df: Drift factor multiplier',
                '0                ',
                '1.0  ',
                'apr: Average atmospheric pressure         ',
                '0        ',
                '74000.0   ',
                'Aep: Albedo extinction coefficient             ',
                '0                ',
                '0.1  ',
                'cc: Canopy coverage fraction         ',
                '0          ',
                '0.7 ',
                'hcan: Canopy height           ',
                '0          ',
                '12.0',
                'lai: Leaf area index',
                '0          ',
                '7.5		',
                'Sbar: Maximum snow load held per unit branch area        ',
                '0               ',
                '6.6',
                'ycage: Forest age flag for wind speed profile parameterization            ',
                '0             ',
                '1.00  ',
                'slope: A 2-D grid that contains the slope at each grid point     ',
                '0          ',
                f'{tslp}',
                'aspect: A 2-D grid that contains the aspect at each grid point   ',
                '0       ',
                f'{azimuth}',
                'latitude: A 2-D grid that contains the latitude at each grid point    ',
                '0             ',
                f'{lat}',
                'subalb: Albedo (fraction 0-1) of the substrate beneath the snow (ground, or glacier)',
                '0',
                '0.25',
                'subtype: Type of beneath snow substrate encoded as (0 = Ground/Non Glacier, 1=Clean Ice/glacier, 2= Debris covered ice/glacier, 3= Glacier snow accumulation zone)',
                '0        ',
                '0.0',
                'gsurf: The fraction of surface melt that runs off (e.g. from a glacier)',
                '0',
                '0.0',
                'b01: Bristow-Campbell B for January (1)',
                '0',
                '6.743      ',
                'b02: Bristow-Campbell B for February (2)',
                '0',
                '7.927    ',
                'b03: Bristow-Campbell B for March(3)',
                '0',
                '8.055  ',
                'b04: Bristow-Campbell B for April (4)',
                '0',
                '8.602 ',
                'b05: Bristow-Campbell B for may (5)',
                '0',
                '8.43  ',
                'b06: Bristow-Campbell B for June (6)',
                '0',
                '9.76',
                'b07: Bristow-Campbell B for July (7)',
                '0',
                '0.0    ',
                'b08:  Bristow-Campbell B for August (8)',
                '0',
                '0.0  ',
                'b09: Bristow-Campbell B for September (9)',
                '0',
                '0.0   ',
                'b10: Bristow-Campbell B for October (10)',
                '0',
                '7.4  ',
                'b11: Bristow-Campbell B for November (11)',
                '0',
                '9.14    ',
                'b12: Bristow-Campbell B for December (12)',
                '0',
                '6.67 ',
                'ts_last:  degree celsius ',
                '0',
                '-9999',
                'longitude: A 2-D grid that contains the latitude at each grid ',
                '0',
                f'{lon}' 
                ]

                with open(site_file, "w") as f:
                    f.writelines('\n'.join(site_var_list))


                input_ctr_list = [
                             'Input Control file',
                             'Prec: Precipitation  (always required)',
                             '3   ',
                             '0',
                             'Ta: Air temperature  (always required)',
                             '3  ',
                             '0',
                             'Tmin: Min Air temperature ',
                             '2',
                             '0',
                             'Tmax: Max Air temperature  ',
                             '2',
                             '0',
                             'v: Wind speed   (always required)',
                             '3',
                             '1',
                             'RH: Relative Humidity   (always required)',
                             '3',
                             '40',
                             'Vp: Air vapor pressure   ',
                             '2',
                             '0.5',
                             'AP: Air pressure   (always required)',
                             '3',
                             '74000			//press Pressure Time 3',
                             'Qsi: Incoming shortwave(kJ/m2/hr)   (only required if irad=1 or 2)',
                             '3',
                             '0             ',
                             'Qli: Long wave radiation(kJ/m2/hr)',
                             '3',
                             '0',
                             'Qnet: Net radiation(kJ/m2/hr)   (only required if irad=3)',
                             '2  ',
                             '0',
                             'Qg: Ground heat flux   (kJ/m2/hr)        ',
                             '2',
                             '0 		    ',
                             'Snowalb: Snow albedo (0-1).  (only required if ireadalb=1) The albedo of the snow surface to be used when the internal albedo calculations are to be overridden',
                             '2',
                             '0.6'
                         ]

                with open(inputctr_file, "w") as f:
                    f.writelines('\n'.join(input_ctr_list))

                output_list = [
             'OUTPUT VARIABLES',
             '1                 // number of point details; put 0 if no point output needed ',
             f'0 0 {catID}_Point00.txt    // y, x coordinates, output file name                       ',
             '0                //number of netcdf outputs; put 0 if no netcdf output needed',
             '0                   //number of aggregated output variables',
             'SWE m AVE           //name/symbol unit Aggregation operation (look up the dictionary "UEB_Variables_Symbols.dat" for the symbol, Operation SUM or AVE)',
             'SWIT m SUM',
             'SWISM m SUM' ]

                with open(outputctr_file, "w") as f:
                    f.writelines('\n'.join(output_list))

                input_list = [
                          'UEBGrid Model Driver Test for TWDEF',
                          param_file,
                          site_file,
                          inputctr_file,
                          outputctr_file,
                          param_dir_source + '/aggout.nc ',
                          param_dir_source + '/watershed_onecell.nc',
                          'watershed y x',
                          f'{startdate[:4]} {startdate[4:6]} {startdate[6:8]} {startdate[8:10]}.0',
                          f'{enddate[:4]} {enddate[4:6]} {enddate[6:8]} {enddate[8:10]}.0',
                          '1.0',
                          '-7.0',
                          '0',
                          '1 15 16',
                          '1 1'
                ]
                with open(input_file, "w") as f:
                    f.writelines('\n'.join(input_list))

#            replace_path( site_file, param_dir_source, [ '1' ] )
#            replace_path( inputctr_file, param_dir_source, [ '0', '1'] )
      

def create_sac_input(
    catids: List[str],
    attr_file: Union[str, Path],
    sac_input_dir: str
)->None:

    """ Create BMI configuration file for Snow17

    Parameters
    ----------
    catids : catchment IDs in the basin
    sac_param_file : sac parameter file
    sac_bmi_dir : directory for the sac bmi configuration file

    Returns
    ----------
    None

    """
    os.makedirs(sac_input_dir, exist_ok=True)

    # Read hydrofabric attribute file
    dfa = pd.read_parquet(attr_file)
    dfa.set_index("divide_id", inplace=True)

    param_list = ['hru_id HHWM8IL HHWM8IU',
            'hru_area 2994.7 1271.3',
            'uztwm 29.7257 31.9842',
            'uzfwm 22.8335 86.7465',
            'lztwm 18.6968 105.763',
            'lzfpm 419.418 956.052',
            'lzfsm 215.932 212.664',
            'adimp 0.0000 0.0000',
            'uzk 0.8910 0.9266',
            'lzpk 0.0032 0.0037',
            'lzsk 0.2551 0.2633',
            'zperc 281.8200 267.7290',
            'rexp 5.2353 5.0608',
            'pctim 0.0000 0.0000',
            'pfree 0.3142 0.2880',
            'riva 0.0100 0.0100',
            'side 0.0000 0.0000',
            'rserv 0.3000 0.3000']

    for catID in catids:
        input_file = os.path.join(sac_input_dir, 'sac-init-' +catID + '-HHWM8.namelist.input')
        param_file = os.path.join(sac_input_dir, 'sac_params-' +catID + '.HHWM8.txt')

        with open(param_file, "w") as f:
            f.writelines('\n'.join(param_list))

        input_list = ['&SAC_CONTROL',
                '! === run control file for sacbmi v. 1.x ===',
                '',
                '! -- basin config and path information',
                'main_id             = "' + catID + '"     ! basin label or gage id',
                'n_hrus              = 1            ! number of sub-areas in model',
                'forcing_root        = "extern/sac-sma/sac-sma/test_cases/ex1/input/forcing/forcing.snow17bmi."',
                'output_root         = ""',
                'sac_param_file   = "' + param_file + '"',
                'output_hrus         = 0            ! output HRU results? (1=yes; 0=no)',
                '',
                '! -- run period information',
                'start_datehr        = 2015120112   ! start date time, backward looking (check)',
                'end_datehr          = 2015123012   ! end date time',
                'model_timestep      = 3600        ! in seconds (86400 seconds = 1 day)',
                '',
                '! -- state start/write flags and files',
                'warm_start_run      = 0  ! is this run started from a state file?  (no=0 yes=1)',
                "write_states        = 0  ! write restart/state files for 'warm_start' runs (no=0 yes=1)",
                '',
                '! -- filenames only needed if warm_start_run = 1',
                'sac_state_in_root  = "../state/sac_states."  ! input state filename root',
                '',
                '! -- filenames only needed if write_states = 1',
                'sac_state_out_root = "../state/sac_states."  ! output states filename root',
                '/',
                ''
                ]
        with open(input_file, "w") as f:
            f.writelines('\n'.join(input_list))

def create_pet_input(
    catids: List[str],
    attr_file: Union[str, Path],
    pet_input_dir: str
)->None:

    """ Create BMI configuration file for pet

    Parameters
    ----------
    catids : catchment IDs in the basin
    pet_input_dir : directory for the pet input files

    Returns
    ----------
    None

    """
    os.makedirs(pet_input_dir, exist_ok=True)

    # Read hydrofabric attribute file
    dfa = pd.read_parquet(attr_file)
    dfa.set_index("divide_id", inplace=True)

    ini_list = ['verbose=0',
                'pet_method=5',
                'forcing_file=BMI',
                'run_unit_tests=0',
                'yes_aorc=1',
                'yes_wrf=0',
                'wind_speed_measurement_height_m=10.0',
                'humidity_measurement_height_m=2.0',
                'vegetation_height_m=0.12',
                'zero_plane_displacement_height_m=0.0003',
                'momentum_transfer_roughness_length=0.0',
                'heat_transfer_roughness_length_m=0.0',
                'surface_longwave_emissivity=1.0',
                'surface_shortwave_albedo=0.22',
                'cloud_base_height_known=FALSE',
                'latitude_degrees=37.25',
                'longitude_degrees=-97.5554',
                'site_elevation_m=303.33',
                'time_step_size_s=3600',
                'num_timesteps=720',
                'shortwave_radiation_provided=0']

    for catID in catids:
        ini_file = os.path.join(pet_input_dir, catID + '_bmi_config.ini')

        with open(ini_file, "w") as f:
            f.writelines('\n'.join(ini_list))
            

def create_lasam_input(
    catids: List[str],
    soil_param_file: str,
    soil_class_file: Union[str, Path],
    lasam_bmi_dir: Union[str, Path], 
)->None:

    """ Create BMI configuration file for Lumped Arid and Semi-arid Model 

    Parameters
    ----------
    catids : catchment IDs in the basin
    cfe_bmi_dir : directory for the cfe bmi configuration file 
    soil_param_file : soil hydraulic parameter file 
    soil_class_file : soil texture class file 
    lasam_bmi_dir : directory for the lasam bmi configuration file 

    Returns 
    ----------
    None

    """

    os.makedirs(lasam_bmi_dir, exist_ok=True)

    # Create lasam list
    lasam_lst = ['verbosity=none',
                'soil_params_file=' + soil_param_file,
               'layer_thickness=200.0[cm]',
               'initial_psi=2000.0[cm]',
               'timestep=300[sec]',
               'endtime=1000[hr]',
               'forcing_resolution=3600[sec]',
               'ponded_depth_max=0[cm]',
               'use_closed_form_G=false',
               'layer_soil_type=',
               'max_soil_types=25',
               'wilting_point_psi=15495.0[cm]',
               'giuh_ordinates=0.55,0.25,0.2',
               'sft_coupled=true',
               'soil_z=10,30,100.0,200.0[cm]',
               'calib_params=true',
               'field_capacity_psi=340.0[cm]',
               ]

    # Read soil class file
    df_soil = pd.read_csv(soil_class_file)
    df_soil.set_index("id", inplace=True)

    # Create bmi config file
    for catID in catids:
        #cfe_file_catID = glob.glob(os.path.join(cfe_bmi_dir, catID + '*.txt'))[0]
        #df = pd.read_table(cfe_file_catID,  delimiter='=', names=["Params","Values"], index_col=0)
        lasam_lst_catID = lasam_lst.copy()
        lasam_lst_catID[9] = lasam_lst_catID[9] + str(df_soil.loc[catID]['category'])
        #lasam_lst_catID[12] = lasam_lst_catID[12] + df.loc['giuh_ordinates'][0]
        lasam_bmi_file = os.path.join(lasam_bmi_dir, catID + '_bmi_config_lasam.txt')

        with open(lasam_bmi_file, "w") as f:
            f.writelines('\n'.join(lasam_lst_catID))


def change_topmodel_input(
    catID: str, 
    runfile: Union[str, Path], 
    paramsfile: Union[str, Path], 
    subcatfile: Union[str, Path], 
    inputDir: Union[str, Path],
)->None:

    """ change options in TOPMODEL input file

    Parameters
    ----------
    catID : catchment ID
    runfile : specify paths for forcing, subcat, parameters, topmodel output and hyd output
    paramsfile : parameter file
    subcatfile : subcat file
    inputDir : directory for storing input files

    Returns 
    ----------
    None   

    """

    # Copy
    new_runfile = os.path.join(inputDir, '{}'.format(catID) + '_topmodel.run')
    shutil.copy(runfile, new_runfile)
    new_params = os.path.join(inputDir, '{}'.format(catID) + '_topmodel_params.dat')
    shutil.copy(paramsfile, new_params)
    new_subcat = os.path.join(inputDir, '{}'.format(catID) + '_topmodel_subcat.dat')
    shutil.copy(subcatfile, new_subcat)

    # read runfile
    with open(new_runfile, 'r') as infile:
         list_lines = infile.readlines()
    lst_lines = copy.deepcopy(list_lines)

    # Change directory in runfile
    topmod_out = os.path.join(os.path.dirname(os.path.dirname(inputDir)), '{}'.format(catID) + '_topmod.out')
    hyd_out = os.path.join(os.path.dirname(os.path.dirname(inputDir)), '{}'.format(catID) + '_hyd.out')
    filePath = [os.path.join(os.path.dirname(inputDir), '{}'.format(catID) + '_forcing.csv'),
                new_subcat, new_params, topmod_out, hyd_out]

    for i in range(0,5):
        lst_lines[i+2] = filePath[i] + '\n'

    # Save file
    with open(new_runfile, 'w') as outfile:
        outfile.writelines(lst_lines)


def create_troute_config(
    gpkg_file: Union[str, Path],
    rt_cfg_file:  Union[str, Path],
    start_date: str,
    nts: int,
    #reformat_dir: Union[str, Path],
)->None:

    """ Create routing configuration YAML file

    Parameters
    ----------
    gpkg_file :  GeoPackage hydrofabric file
    rt_cfg_file : t-route configuration YAML file
    start_date :  start date for restart run 
    nts : number of timesteps
    reformat_dir : directory for the reformatted nexus output files

    Returns
    ----------
    None

    """

    # bmi_parameters 
    bmi_param = {"flowpath_columns": ["id", "toid", "lengthkm"],
                 "attributes_columns": ['attributes_id', 
                                        'rl_gages',
                                        'rl_NHDWaterbodyComID',
                                        'MusK',
                                        'MusX',
                                        'n',
                                        'So',
                                        'ChSlp',
                                        'BtmWdth',
                                        'nCC',
                                        'TopWdthCC',
                                        'TopWdth'],
                 "waterbody_columns": ['hl_link', 
                                       'ifd',
                                       'LkArea',
                                       'LkMxE',
                                       'OrificeA',
                                       'OrificeC',
                                       'OrificeE',
                                       'WeirC',
                                       'WeirE',
                                       'WeirL'],
                 "network_columns": ['network_id', 'hydroseq', 'hl_uri'],
                }

    # log_parameters
    log_param = {"showtiming": True, "log_level": 'DEBUG'}

    # network_topology_parameters
    columns = {"key": "id",  
               "downstream": "toid",
               "dx": "lengthkm",
               "n": "n",
               "ncc": "nCC",
               "s0": "So",
               "bw": "BtmWdth",
               "waterbody": "rl_NHDWaterbodyComID",
               "gages": "rl_gages",
               "tw": "TopWdth",
               "twcc": "TopWdthCC",
               "musk": "MusK",
               "musx": "MusX",
               "cs": "ChSlp",
               "alt": "alt",
              }

    dupseg = ["717696", "1311881", "3133581", "1010832", "1023120", "1813525", 
              "1531545", "1304859", "1320604", "1233435", "11816", "1312051",
              "2723765", "2613174", "846266", "1304891", "1233595", "1996602", 
              "2822462", "2384576", "1021504", "2360642", "1326659", "1826754",
              "572364", "1336910", "1332558", "1023054", "3133527", "3053788",  
              "3101661", "2043487", "3056866", "1296744", "1233515", "2045165", 
              "1230577", "1010164", "1031669", "1291638", "1637751",
             ]

    nwtopo_param = {"supernetwork_parameters": {"network_type": "HYFeaturesNetwork",
                                                "geo_file_path": gpkg_file, 
                                                "columns": columns, 
                                                "duplicate_wb_segments": dupseg},
                    "waterbody_parameters": {"break_network_at_waterbodies": True,
                                             "level_pool": {"level_pool_waterbody_parameter_file_path": gpkg_file}},
                   }

    # compute_parameters
    res_da = {"reservoir_persistence_da":{"reservoir_persistence_usgs": False,
                                           "reservoir_persistence_usace": False},
              "reservoir_rfc_da": {"reservoir_rfc_forecasts": False,
                                   "reservoir_rfc_forecasts_time_series_path": None,
                                   "reservoir_rfc_forecasts_lookback_hours": 28,
                                   "reservoir_rfc_forecasts_offset_hours": 28,
                                   "reservoir_rfc_forecast_persist_days": 11},
              "reservoir_parameter_file": None,
             }
    
    stream_da = {"streamflow_nudging": False,
                 "diffusive_streamflow_nudging": False,
                 "gage_segID_crosswalk_file": None,
                }

    comp_param = {"parallel_compute_method": "by-subnetwork-jit-clustered",
                 "subnetwork_target_size": 10000,
                 "cpu_pool": 16,
                 "compute_kernel": "V02-structured",
                 "assume_short_ts": True,
                 "restart_parameters": {"start_datetime": start_date},
                 "forcing_parameters": {"qts_subdivisions": 12,
                                        "dt": 300,
                                        "qlat_input_folder": ".",
                                        "qlat_file_pattern_filter": "nex-*", 
                                        "nts": nts, 
                                        "max_loop_size": divmod(nts*300, 3600)[0]+1},
                 "data_assimilation_parameters": {"usgs_timeslices_folder": None,
                                                  "usace_timeslices_folder": None,
                                                  "timeslice_lookback_hours": 48, 
                                                  "qc_threshold": 1, 
                                                  "streamflow_da": stream_da,
                                                  "reservoir_da": res_da},  
                 }

    # output_parameters
    output_param = {'stream_output': {'stream_output_directory': ".",
                                      'stream_output_time': divmod(nts*300, 3600)[0]+1,
                                      'stream_output_type': '.nc',
                                      'stream_output_internal_frequency': 60, 
                                       },
                   }

    # Combine all parameters
    config = {"bmi_parameters": bmi_param, 
              "log_parameters": log_param,
              "network_topology_parameters": nwtopo_param,
              "compute_parameters": comp_param,
              "output_parameters": output_param,
             }

    # Save configuration into yaml file
    with open(rt_cfg_file, 'w') as file:
        yaml.dump(config, file, sort_keys=False, default_flow_style=False, indent=4)

def var_mapping(
    modules: List[str],
    pet_in: str,
    pcp_in: str,
)-> Dict[str,str]:
    """ create variable nameing mapping based on modules
    
    Parameters
    ----------
    modules: list of modules in the formulation
    pet_in: module input variable name for evapotranspiration   
    pcp_in: module input variable name for precipitation

    Returns 
    ----------
    Variable name mapping dictionary

    """
    var_maps = {}

    # only needed when CFE is not coupled to SFT/SMP
    if ('cfes' in modules or 'cfex' in modules) and ('sft' not in modules):
        var_maps["ice_fraction_schaake"] = "sloth_ice_fraction_schaake"
        var_maps["ice_fraction_xinanjiang"] = "sloth_ice_fraction_xinanjiang"
        var_maps["soil_moisture_profile"] = "sloth_smp"
        
    # PET
    if 'noah' in modules and 'pet' not in modules:
        var_maps[pet_in] = "EVAPOTRANS"
        
    # snowmelt
    if 'snow17' in modules:
        var_maps[pcp_in] = 'raim' 
    elif 'ueb' in modules:
        var_maps[pcp_in] = "SWIT"    
    elif 'noah' in modules: # check noah last since it can also be included to provided ET
        var_maps[pcp_in] = "QINSUR"         

    return var_maps     

def get_model_type_name(
    module: str            
) -> str:
    return settings.modules_all.loc[settings.modules_all['module']==module,'name_config'].iloc[0]

def create_realization_file(
    workdir: Union[str, Path], 
    lib_file: dict, 
    bmi_dir: dict, 
    forcing_dir: Union[str, Path], 
    realization_file: Union[str, Path],
    modules: List[str], 
    time_period: dict, 
    rt_dict: dict,
)-> None:

    """ Create realization file for the specified model and module

    Parameters
    ----------
    workdir : basin directory for storing all the files 
    lib_file : library files for different modules
    bmi_dir : directory for different model or module to store BMI files 
    forcing_dir : directory to store foricng files
    realization_file : model realization configuration file
    model: model and module combination 
    time_period : simulation and evaluation time period
    rt_dict : routing model source file directory and configuration file  

    Returns 
    ----------
    None

    """

    # Create symlinks for libraries
    lib_mod = {} 
    for key, value in lib_file.items(): 
        lib_mod_link = os.path.join(workdir, 'Input/' + os.path.basename(value))
        lib_mod.update({key: lib_mod_link})
        if not os.path.exists(lib_mod_link): 
            os.symlink(value, lib_mod_link)

    model_configs = {}
    # noah 
    if 'noah' in modules:
        model_configs['noah'] = {"name": "bmi_fortran", 
                     "params": {"name": "bmi_fortran", 
                                "model_type_name": get_model_type_name('noah'), 
                                "main_output_variable": "QINSUR",
                                "library_file": lib_mod['noah'],
                                "init_config": os.path.join(bmi_dir['noah'], '{{id}}_calib.input'),
                                "allow_exceed_end_time": True, "fixed_time_step": False, "uses_forcing_file": False,
                                "variables_names_map": {
                                    "PRCPNONC": "atmosphere_water__liquid_equivalent_precipitation_rate",
                                    "Q2": "atmosphere_air_water~vapor__relative_saturation",
                                    "SFCTMP": "land_surface_air__temperature",
                                    "UU": "land_surface_wind__x_component_of_velocity",
                                    "VV": "land_surface_wind__y_component_of_velocity",
                                    "LWDN": "land_surface_radiation~incoming~longwave__energy_flux",
                                    "SOLDN": "land_surface_radiation~incoming~shortwave__energy_flux",
                                    "SFCPRS": "land_surface_air__pressure"}}}

    # cfe or cfex
    if 'cfes' in modules or 'cfex' in modules:
        m1 = 'cfes' if 'cfes' in modules else 'cfex'
        model_configs[m1] = {"name": "bmi_c",
                                "params": {"name": "bmi_c", 
                                    "model_type_name": get_model_type_name(m1), 
                                    "main_output_variable": "Q_OUT",
                                    "library_file": lib_mod[m1],
                                    "init_config": os.path.join(bmi_dir[m1], '{{id}}_bmi_config_cfe.txt'), 
                                    "allow_exceed_end_time": True, "fixed_time_step": False, "uses_forcing_file": False,
                                    "registration_function": "register_bmi_cfe"}}

        # variable name mapping section
        pet_in = "water_potential_evaporation_flux"
        pcp_in = "atmosphere_water__liquid_equivalent_precipitation_rate"
        model_configs[m1]["params"]["variables_names_map"] = var_mapping(modules, pet_in, pcp_in)

        # module output variable for input to t-route
        main_output_variable = "Q_OUT" 

    # topmodel
    if 'topmodel' in modules:
        model_configs['topmodel'] = {"name": "bmi_c",
                                    "params": {"name": "bmi_c", 
                                        "model_type_name": get_model_type_name('topmodel'), 
                                        "main_output_variable": "Qout",
                                        "library_file": lib_mod['topmodel'],
                                        "init_config": os.path.join(bmi_dir['topmodel'], '{{id}}_topmodel.run'),
                                        "allow_exceed_end_time": True, "fixed_time_step": False, "uses_forcing_file": False,
                                        "registration_function": "register_bmi_topmodel"}}
        # variable name mapping section
        pet_in = "water_potential_evaporation_flux"
        pcp_in = "atmosphere_water__liquid_equivalent_precipitation_rate"
        model_configs['topmodel']["params"]["variables_names_map"] = var_mapping(modules, pet_in, pcp_in)

        # module output variable for input to t-route
        main_output_variable = "Qout"

    # sac-sma
    if 'sac' in modules:
        model_configs['sac'] = {"name": "bmi_fortran",
                                "params": {
                                    "model_type_name": get_model_type_name('sac'),
                                    "library_file": lib_mod['sac'],
                                    "init_config": os.path.join(bmi_dir['sac'], 'sac-init-{{id}}-HHWM8.namelist.input'),
                                    "allow_exceed_end_time": True, "fixed_time_step": False, "uses_forcing_file": False,
                                    "main_output_variable": "tci",
                                }}

        # variable name mapping section
        pet_in = "pet"
        pcp_in = "precip"
        var_maps = var_mapping(modules, pet_in, pcp_in)
        var_maps['tair'] = "land_surface_air__temperature"
        model_configs['sac']["params"]["variables_names_map"] = var_maps

        # module output variable for input to t-route
        main_output_variable = "tci"

    # snow17
    if 'snow17' in modules:
        model_configs['snow17'] = {"name": "bmi_fortran",
                                "params": {
                                    "model_type_name": get_model_type_name('snow17'),
                                    "library_file": lib_mod['snow17'],
                                    "init_config": os.path.join(bmi_dir['snow17'], 'snow17-init-{{id}}.namelist.input'),
                                    "allow_exceed_end_time": True, "fixed_time_step": False, "uses_forcing_file": False,
                                    "main_output_variable": "raim",
                                    "variables_names_map": {
                                        "precip": "atmosphere_water__liquid_equivalent_precipitation_rate",
                                        "tair": "land_surface_air__temperature"
                                    }}}

    #ueb
    if 'ueb' in modules:
        model_configs['ueb'] = {"name": "bmi_c++",
                                "params": {
                                    "name": "bmi_c++", 
                                    "model_type_name": get_model_type_name('ueb'),
                                    "library_file": lib_mod['ueb'],
                                    "init_config": os.path.join(bmi_dir['ueb'], 'ueb-init-{{id}}_calib.dat'),
                                    "allow_exceed_end_time": True, "fixed_time_step": False, "uses_forcing_file": False,
                                    "main_output_variable": "SWIT",
                                    "variables_names_map": {
                                        "Prec": "atmosphere_water__liquid_equivalent_precipitation_rate",
                                        "Ta": "land_surface_air__temperature",
                                        "qair": "atmosphere_air_water~vapor__relative_saturation",
                                        "uebu2d": "land_surface_wind__x_component_of_velocity",
                                        "uebv2d": "land_surface_wind__y_component_of_velocity",
                                        "Qli": "land_surface_radiation~incoming~longwave__energy_flux",
                                        "Qsi": "land_surface_radiation~incoming~shortwave__energy_flux",
                                        "AP": "land_surface_air__pressure"}}}

    #pet 
    if 'pet' in modules:
        model_configs['pet'] = {"name": "bmi_c",
                                "params": {
                                    "model_type_name": get_model_type_name('pet'),
                                    "library_file": lib_mod['pet'],
                                    "init_config": os.path.join(bmi_dir['pet'], '{{id}}_bmi_config.ini'),
                                    "allow_exceed_end_time": True, "fixed_time_step": False, "uses_forcing_file": False,
                                    "main_output_variable": "water_potential_evaporation_flux",
                                    "registration_function": "register_bmi_pet"
                                }}

    # sloth
    if 'sloth' in modules:
        model_configs['sloth'] = {"name": "bmi_c++",
                                "params": {"name": "bmi_c++", 
                                    "model_type_name": get_model_type_name('sloth'), 
                                    "main_output_variable": "z", 
                                    "library_file": lib_mod['sloth'], 
                                    "init_config": '/dev/null',
                                    "allow_exceed_end_time": True, 
                                    "fixed_time_step": False, 
                                    "uses_forcing_file": False}}

        if 'cfes' in modules or 'cfex' in modules :
            if 'sft' not in modules:
                model_params = {
                    "sloth_ice_fraction_schaake(1,double,m,node)": 0.0,
                    "sloth_ice_fraction_xinanjiang(1,double,1,node)": 0.0,
			        "sloth_smp(1,double,1,node)": 0.0}
            else:
                model_params = {
                    "soil_moisture_wetting_fronts(1,double,1,node)": 0.0,
		            "soil_thickness_layered(1,double,1,node)": 0.0,
		            "soil_depth_wetting_fronts(1,double,1,node)": 0.0,
				    "num_wetting_fronts(1,int,1,node)": 1.0,
			        "Qb_topmodel(1,double,1,node)": 0.0,
				    "Qv_topmodel(1,double,1,node)": 0.0,
				    "global_deficit(1,double,1,node)": 0.0}
        elif 'lasam' in modules:
            if 'sft' not in modules:
                model_params = {"soil_temperature_profile(1,double,K,node)" : 275.15}
            else:
                model_params = {
                    "sloth_soil_storage(1,double,m,node)" : 1.0E-10,
                    "sloth_soil_storage_change(1,double,m,node)" : 0.0,
                    "Qb_topmodel(1,double,1,node)": 0.0,
                    "Qv_topmodel(1,double,1,node)": 0.0,
                    "global_deficit(1,double,1,node)": 0.0,
                    "potential_evapotranspiration_rate(1,double,1,node)": 0.0}

        model_configs['sloth']['params'] ['model_params'] = model_params

    # sft
    if 'sft' in modules:
        model_configs['sft'] = {"name": "bmi_c++",
                                "params": {"name": "bmi_c++",
                                    "model_type_name": get_model_type_name('sft'), 
                                    "main_output_variable": "num_cells",
                                    "library_file": lib_mod['sft'],
                                    "init_config": os.path.join(bmi_dir['sft'], '{{id}}_bmi_config_sft.txt'),
                                    "allow_exceed_end_time": True, 
                                    "uses_forcing_file": False,
                                    "variables_names_map": {"ground_temperature" : "TGS"}}}

    # smp
    if 'smp' in modules:
        model_configs['smp'] = {"name": "bmi_c++",
                                "params": {"name": "bmi_c++", 
                                    "model_type_name": get_model_type_name('smp'),
                                    "main_output_variable": "soil_water_table",
                                    "library_file": lib_mod['smp'],
                                    "init_config": os.path.join(bmi_dir['smp'], '{{id}}_bmi_config_smp.txt'),
                                    "allow_exceed_end_time": True,
                                    "uses_forcing_file": False,
                                    "variables_names_map": {
                                        "soil_storage": "SOIL_STORAGE",
				                        "soil_storage_change": "SOIL_STORAGE_CHANGE"}}}
        if 'lasam' in modules:
            model_configs['smp']['params']["variables_names_map"] = {
                                   "soil_storage" : "sloth_soil_storage",
                                   "soil_storage_change" : "sloth_soil_storage_change",
                                   "soil_moisture_wetting_fronts" : "soil_moisture_wetting_fronts",
                                   "soil_depth_wetting_fronts" : "soil_depth_wetting_fronts",
                                   "num_wetting_fronts" : "soil_num_wetting_fronts"}

    # lasam
    if 'lasam' in modules:
        model_configs['lasam'] = {"name": "bmi_c++",
                                "params": {"name": "bmi_c++",
                                    "model_type_name": get_model_type_name('lasam'),
                                    "main_output_variable": "precipitation_rate",
                                    "library_file": lib_mod['lasam'],
                                    "init_config": os.path.join(bmi_dir['lasam'], '{{id}}_bmi_config_lasam.txt'),
                                    "allow_exceed_end_time": True,
                                    "uses_forcing_file": False}}

        # variable name mapping section
        pet_in = "potential_evapotranspiration_rate"
        pcp_in = "precipitation_rate"
        model_configs['lasam']["params"]["variables_names_map"] = var_mapping(modules, pet_in, pcp_in)

        # module output variable for input to t-route
        main_output_variable = "total_discharge"


    # Combine configurations
    model_type_name = '_'.join([m1 for m1 in modules if m1 not in ['sloth','troute']])    
    gbmain = {"name": "bmi_multi", 
              "params": {"name": "bmi_multi", "model_type_name": model_type_name, "init_config": "",
                         "allow_exceed_end_time": False, "fixed_time_step": False, 
                         "uses_forcing_file": False,
                         "main_output_variable": main_output_variable}}



    # modules section    
    gbmain["params"]["modules"] = [model_configs[m1] for m1 in modules if m1 != 'troute']

    # global configuration
    g = {"global": {"formulations": [gbmain],
                    "forcing": {"file_pattern": ".*{{id}}.*.csv", "path": forcing_dir, "provider": "CsvPerFeature"}}}

    # time object
    t = {"time": {"start_time": time_period['run_time_period']['calib'][0],
                  "end_time": time_period['run_time_period']['calib'][1], "output_interval": 3600}}
    g.update(t)

    # routing object 
    g.update(rt_dict)

    # save configuration into json file 
    with open(realization_file, 'w') as outfile:
        json.dump(g, outfile, indent=4, separators=(", ", ": "), sort_keys=False)
    print(f'Realization file is created at {realization_file}')


def create_calib_config_file(
    par_file: Union[str, Path], 
    modules: List[str],
    workdir: Union[str, Path], 
    general_dict: dict,
    model_dict: dict, 
    config_yaml_file: Union[str, Path], 
)->None: 

    """ Create configuration YAML file for calibration run

    Parameters
    ----------
    par_file : file containing min, max and init values of calibration parameters
    modules: list of modules in the formulation
    workdir : basin directory for storing all the files 
    general_dict : general settings  
    model_dict : model settings 
    config_yaml_file : configuration YAML file  

    Returns 
    ----------
    None

    """

    # Extract calibration params range
    # If par_file (which contains calibration parameters and its initial, min and max values) exists,
    # read from that file directly; otherwise gather this information from predefined calib_params files for 
    # individual modules in the directory given by par_file
    calib_modules_config = list(settings.modules_all.loc[settings.modules_all['calibratable'],'name_config'])
    if os.path.isfile(par_file) and os.path.exists(par_file):
        df_params = pd.read_fwf(par_file).copy()
        df_params = df_params.loc[df_params['model'].isin(calib_modules_config)]
    else:
        par_dir = os.path.join(par_file,'')
        if os.path.exists(par_dir):
            df_params = pd.DataFrame()
            for m1 in modules:
                m_ui = settings.modules_all.loc[settings.modules_all['module']==m1,'name_ui'].iloc[0]
                m_config = settings.modules_all.loc[settings.modules_all['module']==m1,'name_config'].iloc[0]
                if m_config in calib_modules_config:
                    f1 = par_dir + '/calib_params_' + m_ui + '.csv'
                    if not os.path.exists(f1):
                        logger.error(f'Folder {par_dir} does not contain calibration parameter file for {m_ui}')
                    df_tmp = pd.read_csv(f1,sep=None,comment='#',engine='python')
                    df_tmp['model'] = m_config
                    df_params = pd.concat([df_params, df_tmp], ignore_index=True)
        else:
            logger.error(f'File {par_file} does not exist and \
                Folder {par_dir} does not exist or does not contain calibration parameter files for the chosen modules')

    if len(df_params) == 0:
        logger.error(f'No calibratable parameters found for the list of modules: {modules}')
    
    df_params.set_index('param', inplace=True)
    calib_params = df_params.groupby('model').groups

    params_range_dict = {}
    for k, v in calib_params.items():
        params_range = []
        for m in v:   
            params_range.append({'name': m, 'min': float(df_params.query('model==@k').loc[m]['min']), 
                                 'max': float(df_params.query('model==@k').loc[m]['max']), 
                                 'init': float(df_params.query('model==@k').loc[m]['init'])})
        params_range_dict.update({k: params_range})

    # Create configuration 
    basin_yaml = {'general': general_dict}
    basin_yaml.update(params_range_dict)

    # Create symlink for ngen executable
    ngen_file_link = os.path.join(workdir, 'Input/' + os.path.basename(model_dict['binary'])[0:4])
    if not os.path.exists(ngen_file_link):
        os.symlink(model_dict['binary'], ngen_file_link)

    model_dict['binary'] = ngen_file_link
    basin_yaml['model'] = model_dict
    basin_yaml['model']['params'] = params_range_dict 

    # Save configuration into yaml file
    with open(config_yaml_file, 'w') as file:
        yaml.dump(basin_yaml, file, sort_keys=False, default_flow_style=False, indent=2)
    print(f'Calibration config file is created at: {config_yaml_file}')
