from typing import ClassVar, Literal, Mapping, Optional

from pydantic import BaseModel, Field

from .bmi_formulation import BMICxx


class SFTParams(BaseModel):
    """Class for validating SFT Parameters"""

    pass


class SFT(BMICxx):
    """A BMIC++ implementation for SFT module"""

    model_params: Optional[SFTParams] = None
    registration_function: str = "none"
    main_output_variable: str = "num_cells"
    model_name: Literal["SFT"] = Field(default="SFT", alias="model_type_name")

    variable_names_map: ClassVar[Mapping[str, str]] = {"ground_temperature": "TG"}
