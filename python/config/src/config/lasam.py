from typing import Literal, Optional

from pydantic import BaseModel, Field

from .bmi_formulation import BMICxx


class LASAMParams(BaseModel):
    """Class for validating LASAM Parameters"""

    pass


class LASAM(BMICxx):
    """A BMIC++ implementation for LASAM module"""

    model_params: Optional[LASAMParams] = None
    registration_function: str = "none"
    main_output_variable: str = "precipitation_rate"
    model_name: Literal["LASAM"] = Field(default="LASAM", alias="model_type_name")
