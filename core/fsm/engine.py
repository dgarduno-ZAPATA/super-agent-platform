from __future__ import annotations

from dataclasses import dataclass

from core.fsm.actions import ActionRegistry, build_default_action_registry
from core.fsm.guards import GuardRegistry, build_default_guard_registry
from core.fsm.schema import FSMConfig


@dataclass(frozen=True, slots=True)
class TransitionResult:
    old_state: str
    new_state: str
    actions_executed: list[str]
    transition_taken: bool
    no_transition_matched: bool = False


class FSMEngine:
    def __init__(
        self,
        config: FSMConfig,
        current_state: str,
        guard_registry: GuardRegistry | None = None,
        action_registry: ActionRegistry | None = None,
    ) -> None:
        if current_state not in config.states:
            raise ValueError(f"unknown current state: '{current_state}'")

        self._config = config
        self._current_state = current_state
        self._guard_registry = (
            build_default_guard_registry() if guard_registry is None else guard_registry
        )
        self._action_registry = (
            build_default_action_registry() if action_registry is None else action_registry
        )

    async def process_event(self, event: str, context: dict[str, object]) -> TransitionResult:
        current_state = self._current_state
        state_config = self._config.states[current_state]

        for transition in state_config.allowed_transitions:
            if transition.event != event:
                continue

            guard_name = transition.guard or "always"
            guard_fn = self._guard_registry.get(guard_name)
            if guard_fn is None:
                raise ValueError(f"unknown guard: '{guard_name}'")
            if not guard_fn(context):
                continue

            action_context = dict(context)
            action_context.update(
                {
                    "event": event,
                    "old_state": current_state,
                    "new_state": transition.target,
                    "guard": guard_name,
                    "current_state": current_state,
                }
            )

            actions_executed: list[str] = []
            await self._execute_actions(state_config.on_exit, action_context, actions_executed)
            await self._execute_actions(transition.actions, action_context, actions_executed)

            new_state_config = self._config.states[transition.target]
            await self._execute_actions(new_state_config.on_enter, action_context, actions_executed)

            self._current_state = transition.target
            return TransitionResult(
                old_state=current_state,
                new_state=self._current_state,
                actions_executed=actions_executed,
                transition_taken=True,
                no_transition_matched=False,
            )

        return TransitionResult(
            old_state=current_state,
            new_state=current_state,
            actions_executed=[],
            transition_taken=False,
            no_transition_matched=True,
        )

    def get_current_state(self) -> str:
        return self._current_state

    def get_allowed_events(self) -> list[str]:
        state_config = self._config.states[self._current_state]
        return sorted({transition.event for transition in state_config.allowed_transitions})

    async def _execute_actions(
        self,
        action_names: list[str],
        context: dict[str, object],
        actions_executed: list[str],
    ) -> None:
        for action_name in action_names:
            action_fn = self._action_registry.get(action_name)
            if action_fn is None:
                raise ValueError(f"unknown action: '{action_name}'")
            await action_fn(context)
            actions_executed.append(action_name)
