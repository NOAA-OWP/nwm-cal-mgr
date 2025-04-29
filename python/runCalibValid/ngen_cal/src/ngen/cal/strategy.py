"""
This module includes several classes to hold algorithm, objective functions and strategy.

@author: Nels Frazer, Xia Feng
"""

from enum import Enum
from pydantic import BaseModel, PyObject, validator, Field
from typing import Optional, Mapping, Any
try: #to get literal in python 3.7, it was added to typing in 3.8
    from typing import Literal
except ImportError:
    from typing_extensions import Literal

from . import metric_functions
#from . import objectives


class Algorithm(str, Enum):
    """Enumeration of supported search algorithms."""
    dds = "dds"
    pso = "pso"
    gwo = "gwo"

class Objective(str, Enum):
    """Enumeration of supported objective functions."""
    __func_map__ = {
                    "kge": metric_functions.KGE,
                    "nse": metric_functions.NSE,
                    "nnse": metric_functions.NSE,
                    "nselog": metric_functions.NSE,
                    "corr": metric_functions.pearson_corr,                    
                    "rmse": metric_functions.root_mean_squared_error,
                    "mae": metric_functions.mean_abs_error,
                    "rsr": metric_functions.rmse_std_ratio,
                    "pbias": metric_functions.percent_bias,
                    "lseg_fdc":metric_functions.pbias_fdc,
                    "hseg_fdc":metric_functions.pbias_fdc,
                    "csi": metric_functions.categorical_score,
                    "far": metric_functions.categorical_score,
                    "pod": metric_functions.categorical_score,
                    "pkbias": metric_functions.event_based_metrics,
                    "pkte": metric_functions.event_based_metrics,
                    "evbias": metric_functions.event_based_metrics,
                }

    kge = "kge"
    nse = "nse"
    nnse = "nnse"
    nselog = "nselog"
    corr = "corr"
    rmse = "rmse"
    mae = "mae"
    rsr = "rsr"
    pbias = "pbias"   
    lseg_fdc = "lseg_fdc"
    hseg_fdc = "hseg_fdc"
    csi = "csi"
    far = "far"
    pod = "pod"
    pkbias = "pkbias"
    pkte = "pkte"
    evbias = "evbias"

    def __call__(self, *args, **kwargs):
        return self.__func_map__[self.value](*args, **kwargs)

class Estimation(BaseModel):
    """Estimation strategy for defining parameter estimation."""
    type: Literal['estimation']

    algorithm: Algorithm
    # parameters: Optional[Mapping[str, Any]] = {}
    parameters: Optional[Mapping[str, Any]] = Field(default=None)

class Sensitivity(BaseModel):
    """Sensitivity strategy for defining a sensitivity analysis"""
    type: Literal['sensitivity']
    pass #Not Implemented
