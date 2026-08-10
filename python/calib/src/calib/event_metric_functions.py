"""
This module contains functions to compute event-based metrics
@author: Yuqiong Liu
"""

import warnings

warnings.simplefilter(action="ignore", category=FutureWarning)
import datetime as dt
from typing import Dict, Optional

import numpy as np
import pandas as pd
from hydrotools.events.event_detection import decomposition as ev
from scipy.signal import find_peaks

__all__ = [
    "identify_events",
    "separate_compound_events",
    "pair_events",
    "compute_event_metrics",
]


def identify_events(
    data: pd.Series,
    halflife: Optional[str] = "6h",
    window: Optional[str] = "7d",
    minimum_event_duration: Optional[str] = "6h",
    start_radius: Optional[str] = "6h",
) -> pd.DataFrame:
    """Conduct first-round event detection using hydrotools.evens.event_detection

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
    events = ev.list_events(
        data,
        halflife=halflife,
        window=window,
        minimum_event_duration=minimum_event_duration,
        start_radius=start_radius,
    )

    if len(events) > 0:
        # Compute peak timing
        events["peak"] = events.apply(
            lambda e: data.loc[e.start : e.end].idxmax(), axis=1
        )

        # Compute peak discharge for each event
        events["peak_value"] = events.apply(
            lambda e: data.loc[e.start : e.end].max(), axis=1
        )

    return events


def separate_compound_events(events: pd.DataFrame, data: pd.Series) -> pd.DataFrame:
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
    data1 = pd.DataFrame({"value": data.values}, index=data.index)

    # Smooth noisy data
    data1["smooth"] = data1["value"].ewm(halflife="6h", times=data1.index).mean()

    # loop throught events already identified
    events_new = pd.DataFrame()
    for e1 in events.itertuples():
        # retrieve the event time series
        df = data1.loc[
            (e1.start - dt.timedelta(hours=6)) : (e1.end + dt.timedelta(hours=6))
        ]

        # get the smoothed time series
        x = df.loc[:, "smooth"]

        # find turning points on the smoothed data
        df.loc[:, "TP"] = (
            (x.shift(-2) < x.shift(-1))
            & (x.shift(-1) < x)
            & (x.shift(1) < x)
            & (x.shift(2) < x.shift(1))
        )

        # identify peaks in original data based on turning points, accounting for time shift caused by smoothing
        peak_times = [
            data1["value"].loc[(t - dt.timedelta(hours=12)) : t].idxmax()
            for t in df.loc[df["TP"], :].index
        ]

        # make sure peak times are within the original event
        peak_times = [t1 for t1 in peak_times if (t1 > e1.start) & (t1 < e1.end)]

        # remove duplicated peak times if any
        tmp = peak_times.copy()
        peak_times = []
        [peak_times.append(p1) for p1 in tmp if p1 not in peak_times]

        # compute start time of new events as the time with the minimum value
        start_times = [e1.start] + [
            data1["value"].loc[peak_times[i1] : peak_times[i1 + 1]].idxmin()
            for i1 in range(len(peak_times) - 1)
        ]

        # end times of new events
        end_times = [t1 - dt.timedelta(hours=1) for t1 in start_times[1:]] + [e1.end]

        # make sure end_time is greater than start_time for every event
        start_times1 = []
        end_times1 = []
        for s, e in zip(start_times, end_times):
            if s < e:
                start_times1 = start_times1 + [s]
                end_times1 = end_times1 + [e]

        # recompute peak times based on start and end times identified
        peak_times = [
            data1["value"].loc[start_times1[i1] : end_times1[i1]].idxmax()
            for i1 in range(len(start_times1))
        ]

        # recompute peak values
        peak_values = [
            data1["value"].loc[start_times1[i1] : end_times1[i1]].max()
            for i1 in range(len(start_times1))
        ]

        # new events from the decomposition
        df_event = pd.DataFrame(
            {
                "start": start_times1,
                "end": end_times1,
                "peak": peak_times,
                "peak_value": peak_values,
            }
        )

        # add new events to dataframe
        events_new = pd.concat([events_new, df_event], ignore_index=True)

    return events_new


def _validate_event_dataframe(
    df: pd.DataFrame,
    name: str,
    required_columns: set[str],
):
    """Validate required columns and start/end ordering."""
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"{name} is missing required columns: {sorted(missing)}")

    # Ensure start/end are datetime
    for col in ["start", "end"]:
        if not pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = pd.to_datetime(df[col], errors="raise")

    # Enforce start < end
    invalid = df[df["start"] >= df["end"]]
    if not invalid.empty:
        raise ValueError(f"{name} contains {len(invalid)} events where start >= end")


def pair_events(
    obs_events: pd.DataFrame,
    mod_events: pd.DataFrame,
    peak_threshold: float,
) -> pd.DataFrame:
    """Pair observed events with model events.

    Observed events with peak_value >= peak_threshold are considered.
    Model events overlapping an observed event are combined.
    If no model event overlaps, a virtual model event is created using the observed event timing.

    Unpaired model events above the threshold are added as symmetric observed–model events.

    Returns
    -------
    DataFrame with columns:
    obs_start, obs_end, mod_start, mod_end

    """
    # check model and observed event dataframes (required columns and start/end ordering)
    _validate_event_dataframe(
        obs_events,
        "obs_events",
        {"start", "end", "peak_value"},
    )
    _validate_event_dataframe(
        mod_events,
        "mod_events",
        {"start", "end", "peak_value"},
    )

    if peak_threshold < 0:
        raise ValueError("peak_threshold must be non-negative")

    # initialize
    obs_events = obs_events.copy()
    mod_events = mod_events.copy()
    mod_events["paired"] = False

    # filter observed events by magnitude (ignore small events)
    obs_events = obs_events.loc[obs_events["peak_value"] >= peak_threshold]

    # initialize output dataframe
    events = pd.DataFrame(
        {
            "obs_start": obs_events["start"].values,
            "obs_end": obs_events["end"].values,
            "mod_start": pd.NaT,
            "mod_end": pd.NaT,
        }
    )

    # pair observed with model events
    for i, obs in events.iterrows():
        overlapping = mod_events.loc[
            (~mod_events["paired"])
            & (mod_events["start"] < obs.obs_end)
            & (mod_events["end"] > obs.obs_start)
        ]

        if not overlapping.empty:
            mod_events.loc[overlapping.index, "paired"] = True
            events.at[i, "mod_start"] = overlapping["start"].min()
            events.at[i, "mod_end"] = overlapping["end"].max()
        else:
            # Virtual model event
            events.at[i, "mod_start"] = obs.obs_start
            events.at[i, "mod_end"] = obs.obs_end

    # unpaired model events
    unpaired = mod_events.loc[
        (~mod_events["paired"]) & (mod_events["peak_value"] >= peak_threshold)
    ]

    if not unpaired.empty:
        # add symmetric observed–model events for unpaired model events
        extra_events = pd.DataFrame(
            {
                "obs_start": unpaired["start"].values,
                "obs_end": unpaired["end"].values,
                "mod_start": unpaired["start"].values,
                "mod_end": unpaired["end"].values,
            }
        )
        events = pd.concat([events, extra_events], ignore_index=True)

    # sort paired events by start time
    events = events.sort_values("obs_start").reset_index(drop=True)

    return events


def compute_event_metrics(
    event_pairs: pd.DataFrame,
    data_obs: pd.Series,
    data_mod: pd.Series,
    aggregation: str,
) -> Dict[str, float]:
    """Compute event-based metrics.

    Given the event pairs identified, compute the three event-based metrics (peak bias, peak timing error,
    event volumn bias). Return either the mean or median of metrics calculated for all events.

    Parameters
    ----------
    event_pairs: paired model and observed events from pair_events()
    data_obs: observed streamflow time series
    data_mod: model streamflow time series
    aggregation: aggregation method (mean or median) for metrics calculated for all events

    Returns
    -------
    Dictionary of event-based metrics: peak_bias, ptime_err, event_bias

    """
    if len(event_pairs) == 0:
        peak_bias = ptime_err = event_bias = np.NaN
    else:
        # get peak magnitude for paired events
        y_pred_peak = event_pairs.apply(
            lambda e: data_mod.loc[e.mod_start : e.mod_end].max(), axis=1
        )
        y_true_peak = event_pairs.apply(
            lambda e: data_obs.loc[e.obs_start : e.obs_end].max(), axis=1
        )

        # get peak timing for paired events
        y_pred_time = event_pairs.apply(
            lambda e: data_mod.loc[e.mod_start : e.mod_end].idxmax(), axis=1
        )
        y_true_time = event_pairs.apply(
            lambda e: data_obs.loc[e.obs_start : e.obs_end].idxmax(), axis=1
        )

        # comptue event volume bias
        pbias = pd.Series(index=range(len(event_pairs)))
        for i1, e1 in enumerate(event_pairs.itertuples()):
            y_pred = data_mod.loc[e1.mod_start : e1.mod_end]
            y_true = data_obs.loc[e1.obs_start : e1.obs_end]
            pbias[i1] = np.abs(y_pred.sum() - y_true.sum()) / y_true.sum() * 100

        if aggregation == "mean":
            peak_bias = (
                np.nanmean(
                    np.absolute(np.subtract(y_pred_peak, y_true_peak) / y_true_peak)
                )
                * 100
            )
            ptime_err = (
                pd.Timedelta(
                    np.timedelta64(
                        np.nanmean(np.absolute(np.subtract(y_pred_time, y_true_time))),
                        "h",
                    )
                ).total_seconds()
                / 3600
            )
            event_bias = pbias.mean()
        elif aggregation == "median":
            peak_bias = (
                np.nanmedian(
                    np.absolute(np.subtract(y_pred_peak, y_true_peak) / y_true_peak)
                )
                * 100
            )
            ptime_err = (
                pd.Timedelta(
                    np.timedelta64(
                        np.nanmedian(
                            np.absolute(np.subtract(y_pred_time, y_true_time))
                        ),
                        "h",
                    )
                ).total_seconds()
                / 3600
            )
            event_bias = pbias.median()
        else:
            warnings.warn("cannot aggregate event-based metrics with " + aggregation)

    return {"peak_bias": peak_bias, "ptime_err": ptime_err, "event_bias": event_bias}
