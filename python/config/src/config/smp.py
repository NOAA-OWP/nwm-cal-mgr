from typing import Any, ClassVar, Literal, Mapping, Optional

from pydantic import Field

from .bmi_formulation import BMICxx


class SMP(BMICxx):
    """A BMIC++ implementation for SMP module"""

    model_params: Optional[Mapping[str, Any]] = None
    registration_function: str = "none"
    main_output_variable: str = "soil_water_table"
    model_name: Literal["SMP"] = Field(default="SMP", alias="model_type_name")

    variable_names_map: ClassVar[Mapping[str, str]] = {
        "soil_storage": "SOIL_STORAGE",
        "soil_storage_change": "SOIL_STORAGE_CHANGE",
    }
