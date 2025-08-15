from typing import ClassVar, Literal, Mapping, Optional

from pydantic import BaseModel, Field

from .bmi_formulation import BMICxx


class UebParams(BaseModel):
    """Class for validating UEB Parameters"""

    # define params which can be adjusted here
    # see cfe.py for example
    tr: Optional[float]
    ts: Optional[float]
    pass


class UEB(BMICxx):
    """A BMIFortran implementation for a UEB module"""

    # NGEN complains about 'model_params' = {} in input...use none to remove it for now
    model_params: Optional[UebParams] = None
    registration_function: str = "none"
    main_output_variable: str = "SWIT"
    # NOTE aliases don't propagate to subclasses, so we have to repeat the alias
    model_name: Literal["UEB"] = Field(
        default="UEB", alias="model_type_name", frozen=True
    )

    variable_names_map: ClassVar[Mapping[str, str]] = {
        "Prec": "atmosphere_water__liquid_equivalent_precipitation_rate",
        "Ta": "land_surface_air__temperature",
        "qair": "atmosphere_air_water~vapor__relative_saturation",
        "uebu2d": "land_surface_wind__x_component_of_velocity",
        "uebv2d": "land_surface_wind__y_component_of_velocity",
        "Qli": "land_surface_radiation~incoming~longwave__energy_flux",
        "Qsi": "land_surface_radiation~incoming~shortwave__energy_flux",
        "AP": "land_surface_air__pressure",
    }
