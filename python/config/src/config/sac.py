from typing import Literal, Optional

from pydantic import BaseModel, Field

from .bmi_formulation import BMIFortran


class SACParams(BaseModel):
    """Class for validating sac-sma Parameters"""

    # define params which can be adjusted here
    # see cfe.py for example
    uztwm: Optional[float] = None
    uzfwm: Optional[float] = None
    lzpk: Optional[float] = None
    rexp: Optional[float] = None


class SAC(BMIFortran):
    """A BMIFortran implementation for a snow17 module"""

    # NGEN complains about 'model_params' = {} in input...use none to remove it for now
    model_params: Optional[SACParams] = None
    main_output_variable: str = "tci_giuh"
    registration_function: str = "register_bmi_sac"
    # NOTE aliases don't propagate to subclasses, so we have to repeat the alias
    model_name: Literal["sac"] = Field(default="sac", alias="model_type_name")
