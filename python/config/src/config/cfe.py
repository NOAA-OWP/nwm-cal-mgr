from typing import ClassVar, Literal, Mapping, Optional

from pydantic import BaseModel, Field

from .bmi_formulation import BMIC


class CFEParams(BaseModel):
    """Class for validating CFE Parameters"""

    maxsmc: Optional[float]
    satdk: Optional[float]
    slope: Optional[float]
    bb: Optional[float]
    multiplier: Optional[float]
    expon: Optional[float]


class CFE(BMIC):
    """A BMIC implementation for the CFE ngen module"""

    model_params: Optional[CFEParams] = None
    main_output_variable: str = "Q_OUT"
    registration_function: str = "register_bmi_cfe"
    # NOTE aliases don't propagate to subclasses, so we have to repeat the alias
    model_name: Literal["CFE"] = Field(default="CFE", alias="model_type_name")

    # can set some default name map entries...will be overridden at construction
    # if a name_map with the same key is passed in, otherwise the name_map
    # will also include these mappings
    variable_names_map: ClassVar[Mapping[str, str]] = {
        # "water_potential_evaporation_flux": "EVAPOTRANS",
        "atmosphere_water__liquid_equivalent_precipitation_rate": "QINSUR"
    }
