""" 
This module contains a variety of functions to create different input files. 

@author: Xia Feng
"""

import copy
import datetime
import glob
import json
import os
#import re
#import sys
import shutil
#import subprocess
import fnmatch
#from fileinput import FileInput
#from functools import partial
from typing import List, Union, Dict
from pathlib import Path
import geopandas as gpd
import pandas as pd
import yaml
import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

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
           'create_noah_input_template',
           'create_sft_smp_input',
           'create_lasam_input',
           'change_lasam_input',
           'create_snow17_input',
           'create_ueb_input',
           'create_sac_input',
           'change_sac_snow17_input',
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
    ### YLiu: read hl_uri info from hydrolocations layer instead of network,
    ### since in oCONUS v2.2 gpkg files, hl_uri is only available in the hydrolocations layer
    #df_network = gpd.read_file(gpkg_file, layer='network')
    #df_network = df_network[['toid','hl_uri']].drop_duplicates()
    #df_network.columns = ['id','hl_uri']
    #df_nexus = df_nexus.merge(df_network, on="id")
    df_hydro = gpd.read_file(gpkg_file, layer='hydrolocations')
    df_hydro = df_hydro[['nex_id','hl_uri']].drop_duplicates()
    df_hydro.columns = ['id','hl_uri']
    df_nexus = df_nexus.merge(df_hydro, on="id")

    df_nexus.set_index('id', inplace=True)
    df_flowpaths = gpd.read_file(gpkg_file, layer='flowpaths')
    df_flowpaths = df_flowpaths.sort_values('hydroseq')
    df_flowpaths.set_index('toid', inplace=True)

    gageid = []
    cw = {}
    for x in df_cat.index:
        nex_id = df_cat.loc[x, 'toid']
        if nex_id not in df_nexus.index:
            continue
        hu_list = df_nexus.loc[nex_id, 'hl_uri']
        if (type(hu_list) is str) or (hu_list is None):
            hu_list = [hu_list]
        elif type(hu_list) is pd.Series:
            hu_list = list(hu_list)
        else:
            raise Exception(f'Unsupported return value for hl_uri; it can only be None, or a string or a series')

        for hu in hu_list:
            if hu is None or not hu.lower().startswith('gage'): 
                catcw = {x: {"Gage_no": ""}}
            elif hu.lower().startswith('gage'):  
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
                        if subdf['id'].iloc[-1].replace('wb','cat') == x:
                            catcw = {x: {"Gage_no": gage}}
                        else:
                            catcw = {x: {"Gage_no": ""}}
                else:
                    catcw = {x: {"Gage_no": ""}}
            cw.update(catcw)
    if len(set(gageid))>1:    
        logger.info(f'More than 1 gage found in hydrofabric GeoPackage file {gpkg_file}')
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


def create_noah_input_template(
    catids: List[str],
    time_period: dict,
    param_dir_source: Union[str, Path],
    input_dir: Union[str, Path],
    template_bmi_dir: Union[str, Path],
)->None:

    """ Create BMI configuration files for Noah-OWP-Modular based on template BMI files provided by the user (or NEDS)

    Parameters
    ----------
    catids : catchment IDs in the basin
    time_period : simulation and evaluation time period
    param_dir_source : source directory containing Noah-OWP-Modular parameter files
    input_dir: directory to save configuration files
    template_bmi_dir: directory to template BMI files

    Returns
    ----------
    None

    """

    # Create symlink for parameter directory
    os.makedirs(input_dir, exist_ok=True)
    noah_par_tables = ['SOILPARM.TBL','MPTABLE.TBL','GENPARM.TBL']
    for par in noah_par_tables:
        src = os.path.join(param_dir_source,par)
        dst = os.path.join(input_dir,par)
        
        with open(src) as f:
            # create a symbolic link for each parameter file
            if os.path.exists(dst) or os.path.islink(dst):
                logger.warning(f'File/link {dst} already exists')
            else:
                os.symlink(src, dst)
                logger.info(f'Creating symlink from {src} to {dst}')

    # Files for the calibration and validation run
    for run_name in ['calib','valid']:
        if time_period['run_time_period'][run_name][0] and time_period['run_time_period'][run_name][1]:

            startdate = time_period['run_time_period'][run_name][0]
            startdate = datetime.datetime.strptime(startdate, "%Y-%m-%d %H:%M:%S") + datetime.timedelta(hours=1)
            startdate = startdate.strftime("%Y%m%d%H%M")
            enddate = datetime.datetime.strptime(time_period['run_time_period'][run_name][1], "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d%H%M")

            # loop through template file for each catchment
            for catID in catids:
                file1 = glob.glob(os.path.join(template_bmi_dir,'*' + catID +'*.input'))
                if len(file1) == 0:
                    raise ValueError(f'No template BMI file found for {catID} in {template_bmi_dir}')
                elif len(file1) > 1:
                    raise ValueError(f'More than one template BMI file found for {catID} in {template_bmi_dir}')
                with open(file1[0]) as f:
                    lines = f.readlines()

                for i1,l1 in enumerate(lines):
                    if 'startdate' in l1:
                        lines[i1] = "  " + "startdate".ljust(19) + "= " + "'" + startdate + "'" + "               ! UTC time start of simulation (YYYYMMDDhhmm)\n"
                    elif 'enddate' in l1:
                        lines[i1] = "  " + "enddate".ljust(19) + "= " + "'" + enddate + "'" + "               ! UTC time end of simulation (YYYYMMDDhhmm)\n"
                    elif 'parameter_dir' in l1:
                        lines[i1] = "  " + "parameter_dir".ljust(19) + "= " + "'" + input_dir + "\n'"

                namelst = os.path.join(input_dir, '{}'.format(catID) + '_' + run_name + '.input')
                with open(namelst, 'w') as outfile:
                    outfile.writelines(lines)

            logger.info(f'noah-owp-modular BMI config files for {run_name} created at {input_dir}/*_{run_name}.input')


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

    param_list = ['hru_id hru2 hru1',
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
        param_file = os.path.join(snow17_input_dir, 'snow17_params-' +catID + '.txt')

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
    ueb_input_dir: str,
    #sitevar_file_exists: bool,
    bmi_dir: Union[str, Path]
)->None:

    """ Create BMI configuration file for ueb

    Parameters
    ----------
    catids : catchment IDs in the basin
    time_period: simulation time period
    attr_file : attributes file containing info on lat/lon/slope/aspect etc
    param_dir_source : directory containing UEB parameter files
    ueb_input_dir : directory for the UEB bmi configuration file
    bmi_dir: directory path containing existing sitevar files (e.g., from EDS)

    Returns
    ----------
    None

   """
    os.makedirs(ueb_input_dir, exist_ok=True)

    # Create symlink for constant parameter files
    const_file_str = ['inputctr','outputctr','params']
    const_files = {}
    for par in const_file_str:
        src = Path(param_dir_source,'ueb_'+par+'.dat').absolute()
        if not os.path.exists(src):
            raise FileNotFoundError(src)
        dst = os.path.join(ueb_input_dir,'ueb_'+par+'.dat')
        const_files.update({par: dst})
        with open(src) as f:
            if not os.path.exists(dst):
                os.symlink(src, dst)
                logger.info(f'Creating symlink from {src} to {dst}')


    # Read hydrofabric attribute file
    dfa = pd.read_parquet(attr_file)
    dfa.set_index("divide_id", inplace=True)

    # sitevars file
    for catID in catids:
        tslp = dfa.loc[catID]['slope_mean']
        azimuth = dfa.loc[catID]['aspect_c_mean']
        lat = dfa.loc[catID]['Y']
        lon = dfa.loc[catID]['X']

        site_file = os.path.join(ueb_input_dir, 'ueb_sitevars-' +catID + '.dat')
        if bmi_dir != '':
            src = glob.glob(os.path.join(bmi_dir, 'ueb_sitevars*' + catID +'*'))
            if len(src) == 0:
                raise ValueError(f'No sitevars file found for {catID} in {bmi_dir}')
            elif len(src)> 1:
                raise ValueError(f'More than one sitevars file found for {catID} in {bmi_dir}')
            with open(src[0]) as f:   
                # create a symbolic link
                if os.path.exists(site_file) or os.path.islink(site_file):
                    pass
                    #logger.warning(f'File/link {dst} already exists')
                else: 
                    os.symlink(src[0], site_file)
                    logger.info(f'Creating symlink from {src[0]} to {site_file}')

        else: # create the sitevars file based on a template file
            temp_file = Path(param_dir_source, 'ueb_sitevars.dat').resolve(strict=True)
            with open(temp_file) as f:
                lines = f.readlines()
            lines[39] = f'{tslp}\n'
            lines[42] = f'{azimuth}\n'
            lines[45] = f'{lat}\n'
            lines[96] = f'{lon}\n'

            with open(site_file, 'w') as outfile:
                outfile.writelines(lines) 

    # ueb-init files need to be created for both calibration and validation runs
    for run_name in ['calib','valid']:
        if time_period['run_time_period'][run_name][0] and time_period['run_time_period'][run_name][1]:
            # Date
            startdate = time_period['run_time_period'][run_name][0]
            startdate = datetime.datetime.strptime(startdate, "%Y-%m-%d %H:%M:%S") + datetime.timedelta(hours=1)
            startdate = startdate.strftime("%Y%m%d%H%M")
            enddate = datetime.datetime.strptime(time_period['run_time_period'][run_name][1], "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d%H%M")
            for catID in catids:
                input_file = os.path.join(ueb_input_dir, 'ueb-init-' +catID + '_' + run_name +'.dat')
                site_file = os.path.join(ueb_input_dir, 'ueb_sitevars-' +catID + '.dat')
                input_list = [
                          'UEBGrid Model Driver Test for TWDEF',
                          const_files['params'],
                          site_file,
                          const_files['inputctr'],
                          const_files['outputctr'],
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

    param_list = ['hru_id hru1 hru2',
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
        input_file = os.path.join(sac_input_dir, 'sac-init-' +catID + '.namelist.input')
        param_file = os.path.join(sac_input_dir, 'sac_params-' +catID + '.txt')

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


def change_sac_snow17_input(
    module: str,
    catids: List[str], 
    input_dir: Union[str, Path],
    bmi_dir: Union[str, Path],
)->None:

    """ copy existing config files for snow17/sac-sma and change path to sac_param_file in snow17/sac-sma namelist input file

    Parameters
    ----------
    module: "sac" or "snow17"
    catids : catchment IDs
    bmi_dir: directory for existing config files
    input_dir : directory for storing new config files

    Returns 
    ----------
    None   

    """
    if module not in ['sac','snow17']:
        raise Exception(f'Model must be either "sac" or "snow17"')
  
    # handle parameter file naming convention 
    str0 = module+'_params_' if module=='sac' else module+'_params-'

    # parameter file entry in namelist file
    str1 = module + "_param_file"

    # create input directory for storing new config files              
    os.makedirs(input_dir, exist_ok=True)

    # loop through all catchments
    for catID in catids:
        
        # existing config files
        namelist_file0 = os.path.join(bmi_dir, module + '-init-{}'.format(catID) + '.namelist.input')
        param_file0 = os.path.join(bmi_dir, str0 + '{}'.format(catID) + '.txt')

        # new config files to be created
        namelist_file = os.path.join(input_dir, module + '-init-{}'.format(catID) + '.namelist.input')
        param_file = os.path.join(input_dir, str0 + '{}'.format(catID) + '.txt')   

        # create symbolic link to the existing sac parameter file     
        if os.path.exists(param_file0):
            os.symlink(param_file0, param_file)
        else:
            raise Exception(f'Parameter file does not exist: {param_file0}')
        
        # correct the path to sac parameter file in namelist input file
        if not os.path.exists(namelist_file0):
            raise Exception(f'Namelist file does not exist: {namelist_file0}')
        with open(namelist_file0) as f:
            lines0 = f.readlines()
        lines1 = copy.deepcopy(lines0)

        idx = [i for i, s in enumerate(lines0) if str1 in s]
        if len(idx) != 1:
            raise Exception(f'No entry or more than one entry found for "{str1}" in namelist input file: {namelist_file0}')
        lines1[idx[0]] = f'{str1}      = "{param_file}"\n'

        # Save to new namelist file
        if os.path.exists(namelist_file):
            raise Exception(f'Namelist file {namelist_file} already exists')
        with open(namelist_file, 'w') as outfile:
            outfile.writelines(lines1)


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
    input_dir: Union[str, Path], 
    param_dir: Union[str, Path],
)->None:

    """ Create BMI configuration file for Lumped Arid and Semi-arid Model 

    Parameters
    ----------
    catids : catchment IDs in the basin
    input_dir : directory for the lasam input configuration file 
    param_dir: directory for static lasam parameter files

    Returns 
    ----------
    None

    """

    os.makedirs(input_dir, exist_ok=True)

    # make sure param_dir and parameter files exist
    if param_dir and os.path.exists(param_dir):
        soil_param_file = os.path.join(param_dir,'vG_default_params.dat')
        if not os.path.exists(soil_param_file):
            raise Exception(f'Soil params file does not exist: {soil_param_file}')
        soil_class_file = os.path.join(param_dir,'lasam_soil_class.txt')
        if not os.path.exists(soil_class_file):
            raise Exception(f'Soil class file does not exist: {soil_class_file}')
    else:
        raise Exception(f'lasam_parameter_dir does not exist: {param_dir}')
    
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
        lasam_bmi_file = os.path.join(input_dir, catID + '_bmi_config_lasam.txt')

        with open(lasam_bmi_file, "w") as f:
            f.writelines('\n'.join(lasam_lst_catID))


def change_lasam_input(
    catids: List[str], 
    input_dir: Union[str, Path],
    bmi_dir: Union[str, Path],
    param_dir: Union[str, Path],
)->None:

    """ copy existing config files for lasam and change path to soil_params_file in lasam config file

    Parameters
    ----------
    catids : catchment IDs
    bmi_dir: directory for existing config files
    input_dir : directory for storing new config files
    param_dir: path to lasam parameter files 

    Returns 
    ----------
    None   

    """
  
    # create input directory for storing new config files              
    os.makedirs(input_dir, exist_ok=True)

    # make sure param_dir exists
    if param_dir and os.path.exists(param_dir):
        param_file = os.path.join(param_dir,'vG_default_params.dat')
        if not os.path.exists(param_file):
            raise Exception(f'Soil_params_file does not exist: {param_file}')
    else:
        raise Exception(f'lasam_parameter_dir does not exist: {param_dir}')

    # loop through all catchments
    for catID in catids:

        # existing config file
        config_file0 = os.path.join(bmi_dir, '{}_bmi_config_lasam'.format(catID) + '.txt')

        # new config file to be created
        config_file = os.path.join(input_dir, '{}_bmi_config_lasam'.format(catID) + '.txt')
        
        # correct the path to soil_params_file in config file
        if not os.path.exists(config_file0):
            raise Exception(f'Namelist file does not exist: {config_file0}')
        with open(config_file0) as f:
            lines0 = f.readlines()
        lines1 = copy.deepcopy(lines0)
        idx = [i for i, s in enumerate(lines0) if "soil_params_file" in s]
        if len(idx) != 1:
            raise Exception(f'No entry or more than one entry found for "soil_params_file" in config file: {config_file0}')
        lines1[idx[0]] = f'soil_params_file={param_file}\n'

        # Save to new config file
        if os.path.exists(config_file):
            raise Exception(f'Config file {config_file} already exists')
        with open(config_file, 'w') as outfile:
            outfile.writelines(lines1)

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
                                        #'rl_gages',
                                        #'rl_NHDWaterbodyComID',
                                        'gage',
                                        'WaterbodyID',
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
               #"waterbody": "rl_NHDWaterbodyComID",
               #"gages": "rl_gages",
               "waterbody": "WaterbodyID",
               "gages": "gage",
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
                                    "init_config": os.path.join(bmi_dir['sac'], 'sac-init-{{id}}.namelist.input'),
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
    logger.info(f'Realization file is created at {realization_file}')


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
    if os.path.isfile(par_file):
        df_params = pd.read_fwf(par_file).copy()
        df_params = df_params.loc[df_params['model'].isin(calib_modules_config)]
    else:
        if os.path.isdir(par_file):
            df_params = pd.DataFrame()
            for m1 in modules:
                m_ui = settings.modules_all.loc[settings.modules_all['module']==m1,'name_ui'].iloc[0]
                m_config = settings.modules_all.loc[settings.modules_all['module']==m1,'name_config'].iloc[0]
                if m_config in calib_modules_config:
                    f1 = os.path.join(par_file, 'calib_params_' + m_ui + '.csv')
                    if not os.path.exists(f1):
                        logger.error(f'Folder {par_file} does not contain calibration parameter file for {m_ui}')
                        continue
                    df_tmp = pd.read_csv(f1,sep=None,comment='#',engine='python')
                    df_tmp['model'] = m_config
                    df_params = pd.concat([df_params, df_tmp], ignore_index=True)
        else:
            raise Exception(f'{par_file} is not a valid file or folder with calibration parameter files for the chosen modules')

    if len(df_params) == 0:
        raise Exception(f'No calibratable parameters found for the list of modules: {modules}')
    
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
    logger.info(f'Calibration config file is created at: {config_yaml_file}')
