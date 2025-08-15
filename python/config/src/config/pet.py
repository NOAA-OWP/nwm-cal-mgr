from typing import Any, ClassVar, Literal, Mapping, Optional

from pydantic import Field

from .bmi_formulation import BMIC


class PET(BMIC):
    """A C implementation of several ET calculation algorithms"""

    # should all be reasonable defaults for pET
    model_params: Optional[Mapping[str, Any]] = None
    main_output_variable: Literal["water_potential_evaporation_flux"] = (
        "water_potential_evaporation_flux"
    )
    # NOTE aliases don't propagate to subclasses, so we have to repeat the alias
    model_name: Literal["PET"] = Field(default="PET", alias="model_type_name")

    variable_names_map: ClassVar[Mapping[str, str]] = {
        "water_potential_evaporation_flux": "water_potential_evaporation_flux"
    }
