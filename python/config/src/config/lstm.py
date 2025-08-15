from typing import Any, ClassVar, Literal, Mapping, Optional, Union

from pydantic import Field
from pydantic.types import ImportString

from .bmi_formulation import BMIPython


class LSTM(BMIPython):
    """A BMIPython implementation for an ngen LSTM module"""

    # should all be reasonable defaults for LSTM
    model_params: Optional[Mapping[str, Any]] = None
    python_type: Union[ImportString, str] = "bmi_lstm.bmi_LSTM"
    main_output_variable: Literal["land_surface_water__runoff_depth"] = (
        "land_surface_water__runoff_depth"
    )
    # NOTE aliases don't propagate to subclasses, so we have to repeat the alias
    model_name: Literal["LSTM"] = Field(default="LSTM", alias="model_type_name")

    variable_names_map: ClassVar[Mapping[str, str]] = {
        "atmosphere_water__time_integral_of_precipitation_mass_flux": "RAINRATE"
    }
