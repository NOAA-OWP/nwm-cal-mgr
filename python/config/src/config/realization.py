from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from pydantic import BaseModel, Field, field_serializer

from .configurations import Forcing, Routing, Time
from .formulation import Formulation


class Realization(BaseModel):
    """Simple model of a Realization, containing formulations and forcing"""

    formulations: Sequence[Formulation]
    forcing: Forcing
    calibration: Optional[Mapping[str, Sequence[Any]]] = None

    def resolve_paths(self):
        for f in self.formulations:
            f.resolve_paths()
        if self.forcing:
            self.forcing.resolve_paths()


class CatchmentRealization(Realization):
    forcing: Optional[Forcing]


class NgenRealization(BaseModel):
    """A complete ngen realization confiiguration model, including global and catchment overrides"""

    global_config: Realization = Field(alias="global")
    time: Time
    routing: Optional[Routing] = None
    # FIXME have not tested catchments...
    catchments: Optional[Mapping[str, CatchmentRealization]] = Field(default_factory=dict)

    # FIXME https://github.com/samuelcolvin/pydantic/issues/2277
    # Until 1.10, it looks like nested encoder config doesn't apply
    # so you have to define the encoder at the top level object that
    # will be serialized...
    class Config:
        validate_by_name = True

        # json_encoders = {datetime: lambda v: v.strftime("%Y-%m-%d %H:%M:%S")}
        @field_serializer("timestamp")
        def serialize_dt(self, dt: datetime) -> str:
            return dt.strftime("%Y-%m-%d %H:%M:%S")

    def resolve_paths(self):
        """resolve possible relative paths in configuration"""
        self.global_config.resolve_paths()
        for k, v in self.catchments.items():
            v.resolve_paths()
        if self.routing is not None:
            self.routing.resolve_paths()
