from typing import Literal, Optional

from pydantic import BaseModel, Field

from .bmi_formulation import BMIC


class TopmodParams(BaseModel):
    """Class for validating Topmod Parameters"""

    sr0: Optional[float] = None
    srmax: Optional[float] = None
    szm: Optional[float] = None
    t0: Optional[float] = None
    td: Optional[float] = None


class Topmod(BMIC):
    """A BMIC implementation for the Topmod ngen module"""

    model_params: Optional[TopmodParams] = None
    main_output_variable: str = "Qout"
    registration_function: str = "register_bmi_topmodel"
    # NOTE aliases don't propagate to subclasses, so we have to repeat the alias
    model_name: Literal["TOPMODEL"] = Field(default="TOPMODEL", alias="model_type_name")
