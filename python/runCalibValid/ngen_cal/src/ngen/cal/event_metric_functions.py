"""
This module contains functions to compute event-based metrics
@author: Yuqiong Liu
"""

import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)
import pandas as pd
import numpy as np
import datetime as dt
from typing import Optional, Dict
from hydrotools.events.event_detection import decomposition as ev

__all__ = ['identify_events',
           'separate_compound_events',
           'pair_events',
           'compute_event_metrics',
          ]

def identify_events(
    data:pd.Series,
    halflife:Optional[str] = '6h', 
    window: Optional[str] = '7d', 
    minimum_event_duration: Optional[str] = '6h',
    start_radius: Optional[str] = '6h',
) -> pd.DataFrame:
    """ Conduct first-round event detection using hydrotools.evens.event_detection

    Parameters
    ----------
    data : streamflow time series 
    halflife: parameter for event detection
    window: parameter for event detection
    minimum_event_duration: parameter for event detection
    start_radius: parameter for event detection 

    Returns
    -------
    DataFrame of events with start, end, and peak times, as well as peak flow value

    """

    # Detect events
    events = ev.list_events(data, halflife=halflife, window=window, 
       minimum_event_duration=minimum_event_duration,start_radius=start_radius)

    if len(events) > 0:

        # Compute peak timing
        events['peak'] = events.apply(lambda e: data.loc[e.start:e.end].idxmax(), axis=1)

        # Compute peak discharge for each event
        events['peak_value'] = events.apply(lambda e: data.loc[e.start:e.end].max(), axis=1)

    return events


def separate_compound_events(
    events:pd.DataFrame, 
    data:pd.Series
) -> pd.DataFrame:
    """
    Separate compound/multi-peak events (from event_detection) into individual single-peak events

    Parameters:
    -----------
    events: initial events detected by event_detection()
    data: the original streamflow time sereies

    Returns:
    -----------
    Single-peak events discretized from compound/multi-peak events
    
    """
    pd.options.mode.chained_assignment = None

    # convert data from Series to Dataframe
    data1 = pd.DataFrame({'value':data.values},index=data.index)
    
    # Smooth noisy data
    data1['smooth']= data1['value'].ewm(halflife='6h', times=data1.index).mean()

    # loop throught events already identified
    events_new = pd.DataFrame()
    for e1 in events.itertuples():

        # retrieve the event time series
        df = data1.loc[(e1.start-dt.timedelta(hours=6)):(e1.end+dt.timedelta(hours=6))]

        # get the smoothed time series
        x = df.loc[:,'smooth']

        # find turning points on the smoothed data
        df.loc[:,'TP'] = ((x.shift(-2) < x.shift(-1)) & (x.shift(-1) < x) & \
                  (x.shift(1) < x) & (x.shift(2) < x.shift(1)))

        # identify peaks in original data based on turning points, accounting for time shift caused by smoothing
        peak_times = [data1['value'].loc[(t-dt.timedelta(hours=12)):t].idxmax() \
              for t in df.loc[df['TP'],:].index]

        # make sure peak times are within the original event
        peak_times = [t1 for t1 in peak_times if (t1>e1.start) & (t1<e1.end)]

        # remove duplicated peak times if any
        tmp = peak_times.copy()
        peak_times = []
        [peak_times.append(p1) for p1 in tmp if p1 not in peak_times]

        # compute start time of new events as the time with the minimum value
        start_times = [e1.start] + [data1['value'].loc[peak_times[i1]:peak_times[i1+1]].idxmin() \
               for i1 in range(len(peak_times)-1)]

        # end times of new events
        end_times = [t1-dt.timedelta(hours=1) for t1 in start_times[1:]] + [e1.end]

        # recompute peak times based on start and end times identified
        peak_times = [data1['value'].loc[start_times[i1]:end_times[i1]].idxmax() \
                for i1 in range(len(start_times))]
        
        # recompute peak values
        peak_values = [data1['value'].loc[start_times[i1]:end_times[i1]].max() \
                for i1 in range(len(start_times))]      
        
        # new events from the decomposition
        df_event = pd.DataFrame({'start':start_times, 'end':end_times, 'peak':peak_times, 'peak_value':peak_values})

        # add new events to dataframe
        events_new = pd.concat([events_new,df_event],ignore_index=True)

    return events_new


def pair_events(
    events1:pd.DataFrame, 
    events2:pd.DataFrame, 
    threshold: np.float64
) -> pd.DataFrame:
    """ 
    Pair observed events with model events

    For every observed event that's above the defined threshold, identify the model events that overlap with 
    the observed event and combine the model events if there is more than one. If no model event identified, 
    set the model event start/end times to the observed event start/end times. 

    Parameters
    ----------
    events1: events for observed streamflow
    events2 : events for model streamflow
    threshold: non-exceedance probablility threshold for events; events with peak magnitude below the threshold are ignored.

    Returns
    -------
    Paired events with columns: obs_start, obs_end, mod_start, mod_end

    """

    # start with labelling all model events as unpaired
    events2_new = events2.copy(deep=True)
    events2_new['paired'] = False

    # process only observed events that are above the defined threshold
    events1_new = events1.loc[events1['peak_value'] >= threshold]

    # create a dataframe for the paired events
    events = events1_new[['start','end']].copy(deep=True)
    events.columns = ['obs_' + s1 for s1 in events.columns]
    events['mod_start'] = np.NaN
    events['mod_end'] = np.NaN

    # loop through observed events
    for e in events1_new.itertuples():

        # identify model events that are overlapping with the current observed event
        # if more than one model events ientified for a given obs event, combine the model events
        events2_new1 = events2_new.loc[~events2_new.paired].copy(deep=True)
        for e1 in events2_new1.itertuples():
            if max(e.start, e1.start) < min(e.end, e1.end):
                events2_new.at[e1.Index, 'paired'] = True    
                events.at[e.Index,'mod_start'] = e1.start if pd.isna(events.loc[e.Index,'mod_start']) \
                    else min(e1.start, events.loc[e.Index,'mod_start'])
                events.at[e.Index,'mod_end'] = e1.end if pd.isna(events.loc[e.Index,'mod_end']) \
                    else max(e1.end, events.loc[e.Index,'mod_end'])
                #events.at[e.Index,'mod_peak'] = e1.peak if pd.isna(events.loc[e.Index,'mod_peak']) \
                #    else max(e1.peak, events.loc[e.Index,'mod_peak'])
    
        # if no model events found, create a virtual model event based on the observed event start/end times
        if pd.isna(events.loc[e.Index, 'mod_start']):
            events.at[e.Index,'mod_start'] = events.at[e.Index,'obs_start']
            events.at[e.Index,'mod_end'] = events.at[e.Index,'obs_end']


    # for each unpaired model event (that is above threshold), add an observed event with the same start/end time as the model event
    events2_new1 = events2_new.loc[~events2_new.paired].copy(deep=True)
    if len(events2_new1)>0:
        events2_new1 = events2_new1.loc[events2_new1['peak_value'] >= threshold]
        if events2_new1.shape[0] > 0:
            for e1 in events2_new1.itertuples():
                new_event = pd.DataFrame([{'obs_start':e1.start,'obs_end':e1.end,'mod_start':e1.start,'mod_end':e1.end}])
                events = pd.concat([events, new_event], ignore_index=True)

    # sort paired events by start time
    events = events.sort_values(by=['obs_start']) 
    events = events.reset_index(drop=True)   

    return events

def compute_event_metrics(
    event_pairs:pd.DataFrame, 
    data_obs:pd.Series, 
    data_mod:pd.Series, 
    aggregation:str,
) -> Dict[str, float]:
    """
    Given the event pairs identified, compute the three event-based metrics (peak bias, peak timing error, 
    event volumn bias). Return either the mean or median of metrics calculated for all events.
    
    Parameters:
    ----------------
    events_pairs: paried model and observed events from pair_events()
    data_obs: observed streamflow time series
    data_mod: model streamflow time series
    aggregation: aggregation method (mean or median) for metrics calculated for all events

    """
    if len(event_pairs)==0:
        peak_bias = ptime_err = event_bias = np.NaN 
    else:
        # get peak magnitude for paired events
        y_pred = event_pairs.apply(lambda e: data_obs.loc[e.obs_start:e.obs_end].max(), axis=1)
        y_true = event_pairs.apply(lambda e: data_mod.loc[e.mod_start:e.mod_end].max(), axis=1)

        # get peak timing for paired events
        y_pred_time = event_pairs.apply(lambda e: data_obs.loc[e.obs_start:e.obs_end].idxmax(), axis=1)
        y_true_time = event_pairs.apply(lambda e: data_mod.loc[e.mod_start:e.mod_end].idxmax(), axis=1)

        # comptue event volume bias
        pbias = pd.Series(index=range(len(event_pairs)))
        for i1, e1 in enumerate(event_pairs.itertuples(),1):
            y_pred = data_mod.loc[e1.mod_start:e1.mod_end]
            y_true = data_obs.loc[e1.obs_start:e1.obs_end]
            pbias[i1-1] = np.abs(y_pred.sum()-y_true.sum())/y_true.sum()*100
    
        if aggregation == 'mean':
            peak_bias = np.mean(np.absolute(np.subtract(y_pred, y_true)/y_true))*100
            ptime_err = pd.Timedelta(np.timedelta64(np.mean(np.absolute(np.subtract(y_pred_time, y_true_time))),'h')).total_seconds()/3600
            event_bias = pbias.mean()
        elif aggregation == 'median':
            peak_bias = np.nanmedian(np.absolute(np.subtract(y_pred, y_true)/y_true))*100
            ptime_err = pd.Timedelta(np.timedelta64(np.nanmedian(np.absolute(np.subtract(y_pred_time, y_true_time))),'h')).total_seconds()/3600
            event_bias = pbias.median()
        else:
            warnings.warn("cannot aggregate event-based metrics with " + aggregation)

    return {'peak_bias':peak_bias, 'ptime_err':ptime_err, 'event_bias':event_bias}