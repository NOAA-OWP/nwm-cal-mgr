# Monkey patch pydantic to allow schema serialization of ImportString types to string
from pydantic.types import ImportString


def ImportString_schema(cls, field_schema):
    field_schema["type"] = "string"


ImportString.__modify_schema__ = classmethod(ImportString_schema)

from . import gwo_global_best, gwo_swarms, plot_functions, plot_output
from .calibratable import Adjustable, Calibratable, Evaluatable
from .calibration_set import CalibrationSet, UniformCalibrationSet
from .configuration import General, Model
from .meta import JobMeta
from .plot_functions import (
    barplot_metric,
    plot_cost_hist,
    plot_fdc_calib,
    plot_fdc_valid,
    plot_output,
    plot_streamflow,
    plot_streamflow_precipitation,
    scatterplot_objfun,
    scatterplot_objfun_metric,
    scatterplot_streamflow,
    scatterplot_var,
    trim_axs,
)
from .validation_run import run_valid_ctrl_best
