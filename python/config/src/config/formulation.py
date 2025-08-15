from pydantic import BaseModel, ConfigDict, Field


class Formulation(BaseModel):
    """Model of an ngen formulation"""

    model_config = ConfigDict()
    # TODO make this an enum?
    name: str
    params: "KnownFormulations" = Field(discriminator="model_name")

    def resolve_paths(self):
        self.params.resolve_paths()


# NOTE To avoid circular import and support recrusive modules
# note that `params` is one of KnownFormulations,
# of which MultiBMI may be one of those.
# A MultiBMI has a sequence of Formulation objects, making a recursive type
# So we defer type cheking and importing the KnownFormulations until after
# MultiBMI is defined, then update_forward_refs() (changed to model_rebuild in pydantic v2)
from .all_formulations import KnownFormulations

# Formulation.update_forward_refs()
# Formulation.model_rebuild()
