from typing import ClassVar, Literal, Mapping, Optional, Union

from pydantic import BaseModel, Field
from pydantic.types import ImportString

from .bmi_formulation import BMIPython


class TopoFlowParams(BaseModel):
    """Class for validating TopoFLow Parameters"""

    T_rain_snow: Optional[float] = None


class BmiTopoflowGlacier(BMIPython):
    """A BMIC implementation for the TopoFlow ngen module"""

    model_params: Optional[TopoFlowParams] = None
    python_type: Union[ImportString, str] = "topoflow_glacier.bmi.bmi_topoflow_glacier.BmiTopoflowGlacier"
    main_output_variable: str = "channel_water_x-section__volume_flow_rate"
    # NOTE aliases don't propagate to subclasses, so we have to repeat the alias
    model_name: Literal["BmiTopoflowGlacier"] = Field(default="BmiTopoflowGlacier", alias="model_type_name")

    # can set some default name map entries...will be overridden at construction
    # if a name_map with the same key is passed in, otherwise the name_map
    # will also include these mappings
    variable_names_map: ClassVar[Mapping[str, str]] = {
        "streamflow_cms": "channel_water_x-section__volume_flow_rate", 
        "atmosphere_water__precipitation_leq-volume_flux": "atmosphere_water__liquid_equivalent_precipitation_rate"
    }
