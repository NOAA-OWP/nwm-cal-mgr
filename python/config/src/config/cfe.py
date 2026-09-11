from typing import Literal, Optional

from pydantic import BaseModel, Field

from .bmi_formulation import BMIC


class CFEParams(BaseModel):
    """Class for validating CFE Parameters"""

    maxsmc: Optional[float] = None
    satdk: Optional[float] = None
    slope: Optional[float] = None
    bb: Optional[float] = None
    multiplier: Optional[float] = None
    expon: Optional[float] = None


class CFE(BMIC):
    """A BMIC implementation for the CFE ngen module"""

    model_params: Optional[CFEParams] = None
    main_output_variable: str = "Q_OUT"
    registration_function: str = "register_bmi_cfe"
    # NOTE aliases don't propagate to subclasses, so we have to repeat the alias
    model_name: Literal["CFE"] = Field(default="CFE", alias="model_type_name")
