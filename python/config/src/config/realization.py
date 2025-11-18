from datetime import datetime
from typing import Any, Mapping, Optional, Sequence, Dict

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


class CatchmentGroup(BaseModel):
    formulations: str
    forcing: Optional[str] = None


class NgenRealization(BaseModel):
    """A complete ngen realization confiiguration model, including global, catchment, and grouped overrides"""

    global_config: Optional[Realization] = Field(alias="global", default=None)
    time: Time
    routing: Optional[Routing] = None
    formulation_groups: Optional[Dict[str, Sequence[Formulation]]] = Field(default_factory=dict)
    forcing_groups: Dict[str, Forcing] = Field(default_factory=dict)
    catchments: Optional[Mapping[str, "CatchmentGroup"]] = Field(default_factory=dict)

    class Config:
        validate_by_name = True

        # json_encoders = {datetime: lambda v: v.strftime("%Y-%m-%d %H:%M:%S")}
        @field_serializer("timestamp")
        def serialize_dt(self, dt: datetime) -> str:
            return dt.strftime("%Y-%m-%d %H:%M:%S")

    def resolve_paths(self):
        """resolve possible relative paths in configuration"""
        # Resolve global formulation paths
        if self.global_config is not None:
            self.global_config.resolve_paths()

        # Resolve grouped formulation paths
        for grp, formulations in self.formulation_groups.items():
            for f in formulations:
                f.resolve_paths()

        # Resolve forcing groups
        for grp, forcing in self.forcing_groups.items():
            forcing.resolve_paths()

        if self.routing:
            self.routing.resolve_paths()
