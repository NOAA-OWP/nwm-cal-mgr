from typing import Any, Literal, Mapping, Optional, Sequence

from pydantic import ConfigDict, Field, model_validator

from .bmi_formulation import BMIParams


class MultiBMI(BMIParams):
    """A MultiBMI model definition
    Implements and overrids several BMIParams attributes,
    and includes a recursive Formulation list `modules`
    """

    model_config = ConfigDict()
    # required
    # Due to a recursive formulation definition, have to postpone this
    # type definition and use `update_forward_refs`
    modules: Sequence["Formulation"]
    # defaults
    name: Literal["bmi_multi"] = "bmi_multi"

    # strictly optional (can be none/null)
    # NOTE this is derived from the list of modules
    main_output_variable: Optional[str]
    # NOTE aliases don't propagate to subclasses, so we have to repeat the alias
    # model_name: Optional[str] = Field(alias="model_type_name")
    model_name: Literal["bmi_multi"] = Field("bmi_multi", alias="model_type_name")

    # override const since these shouldn't be used for multi bmi, but are currently
    # required to exist as keys for ngen
    config: Literal[""] = Field("", alias="init_config")
    config_prefix: Optional[str] = Field(None, alias="config_prefix")
    name_map: Optional[Mapping[str, str]] = None  # not relevant for multi-bmi
    model_params: Optional[Mapping[str, Any]] = None  # not relevant for multi-bmi

    def resolve_paths(self):
        for m in self.modules:
            m.resolve_paths()

    @model_validator(mode="before")
    def build_model_name(cls, values: Mapping[str, Any]):
        """Construct the model name, if none provided.

            If no model name is provided, the multiBMI model_type_name
            is constructed by joining each module's name using `_`

        Args:
            values (Mapping[str, Any]): Attributes to assgign to the class, including all defaults

        Returns:
            Mapping[str, Any]: Attributes to assign to the class, with a (possibly) modifed `model_name`
        """
        name = values.get("model_name")
        modules = values.get("modules")
        if not name and modules:
            try:
                names = [m["params"]["model_name"] for m in modules]
            except KeyError:
                names = [m["params"]["model_type_name"] for m in modules]
            values["model_name"] = "_".join(names)
        return values

    @model_validator(mode="before")
    def pick_main_output(cls, values: Mapping[str, Any]) -> Mapping[str, Any]:
        """Determine the main_output_variable, if none is provided.

            If no main_output_variable is provided to the class, the value
            is selected from the LAST module provided in the `modules` input.

        Args:
            values (Mapping[str, Any]): Attributes to assgign to the class, including all defaults

        Returns:
            Mapping[str, Any]: Attributes to assign to the class, with a (possibly) modifed `main_output_variable`
        """
        var = values.get("main_output_variable")
        modules = values.get("modules")
        if not var and modules:
            values["main_output_variable"] = modules[-1]["params"][
                "main_output_variable"
            ]
        return values


# NOTE To avoid circular import and support recrusive modules
# note the `modules` is a sequence of Formulations
# which has a `params` of type KnownFormulations
# of which MultiBMI may be one of those.  So we defer
# type cheking and importing the Formulation until after
# MultiBMI is defined, then update_forward_refs()
# from ngen.config.formulation import Formulation
from .formulation import Formulation

# MultiBMI.update_forward_refs()
# MultiBMI.model_rebuild()
