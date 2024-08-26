from typing import Literal, Optional
from pydantic import BaseModel, Field

from .bmi_formulation import BMIFortran


class SACParams(BaseModel):
    """Class for validating snow17 Parameters
    """
    #define params which can be adjusted here
    #see cfe.py for example
    uztwm: Optional[float]
    uzfwm: Optional[float]
    lzpk: Optional[float]
    rexp: Optional[float]

class SAC(BMIFortran):
    """A BMIFortran implementation for a snow17 module
    """
    #NGEN complains about 'model_params' = {} in input...use none to remove it for now
    model_params: SACParams = None
    main_output_variable: str = 'z'
    #NOTE aliases don't propagate to subclasses, so we have to repeat the alias
    model_name: Literal["sac"] = Field("sac", const=True, alias="model_type_name")

    _variable_names_map =  {
            "precip": "atmosphere_water__liquid_equivalent_precipitation_rate",
            "tair": "land_surface_air__temperature",
            "pet": "water_potential_evaporation_flux"
        }
