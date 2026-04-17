from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FSMStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class TransitionConfig(FSMStrictModel):
    target: str = Field(min_length=1)
    event: str = Field(min_length=1)
    guard: str | None = Field(default=None, min_length=1)
    actions: list[str] = Field(default_factory=list)


class StateConfig(FSMStrictModel):
    description: str = Field(min_length=1)
    allowed_transitions: list[TransitionConfig] = Field(default_factory=list)
    on_enter: list[str] = Field(default_factory=list)
    on_exit: list[str] = Field(default_factory=list)
    timeout_minutes: int | None = Field(default=None, ge=1)
    timeout_target: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_timeout_pair(self) -> StateConfig:
        if self.timeout_target is not None and self.timeout_minutes is None:
            raise ValueError("timeout_minutes is required when timeout_target is provided")
        if self.timeout_minutes is not None and self.timeout_target is None:
            raise ValueError("timeout_target is required when timeout_minutes is provided")
        return self


class FSMConfig(FSMStrictModel):
    initial_state: str = Field(default="idle", min_length=1)
    states: dict[str, StateConfig]

    @model_validator(mode="after")
    def validate_state_targets(self) -> FSMConfig:
        known_states = set(self.states)

        if self.initial_state not in known_states:
            raise ValueError(f"initial_state '{self.initial_state}' references unknown state")

        for state_name, state_config in self.states.items():
            for transition in state_config.allowed_transitions:
                if transition.target not in known_states:
                    raise ValueError(
                        f"state '{state_name}' references unknown transition target "
                        f"'{transition.target}'"
                    )

            timeout_target = state_config.timeout_target
            if timeout_target is not None and timeout_target not in known_states:
                raise ValueError(
                    f"state '{state_name}' references unknown timeout target " f"'{timeout_target}'"
                )

        return self
