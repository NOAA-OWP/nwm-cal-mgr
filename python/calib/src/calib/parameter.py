"""
This is a class to hold the name, initial, minimum and maximum values of calibration parameters.

@author: Nels Frazer
"""

from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field


class Parameter(BaseModel):
    """
    The data class for a given parameter
    """

    model_config = ConfigDict(populate_by_name=True)
    name: str = Field(alias="param")
    min: float
    max: float
    init: float


Parameters = Sequence[Parameter]
