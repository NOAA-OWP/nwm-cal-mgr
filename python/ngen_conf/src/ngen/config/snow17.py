from typing import Literal, Optional
from pydantic import BaseModel, Field

from .bmi_formulation import BMIFortran


class Snow17Params(BaseModel):
    """Class for validating snow17 Parameters
    """
    #define params which can be adjusted here
    #see cfe.py for example4
    mfmin: Optional[float]
    mfmax: Optional[float]
    udaj: Optional[float]
    pxtemp: Optional[float]
    timp: Optional[float]
    

class Snow17(BMIFortran):
    """A BMIFortran implementation for a snow17 module
    """
    #NGEN complains about 'model_params' = {} in input...use none to remove it for now
    model_params: Snow17Params = None
    main_output_variable: str = 'raim'
    #NOTE aliases don't propagate to subclasses, so we have to repeat the alias
    model_name: Literal["snow17"] = Field("snow17", const=True, alias="model_type_name")

    _variable_names_map =  {
            "precip": "atmosphere_water__liquid_equivalent_precipitation_rate",
            "tair": "land_surface_air__temperature"
        }
