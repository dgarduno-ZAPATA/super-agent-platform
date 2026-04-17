from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from core.fsm.schema import FSMConfig


def test_example_fsm_yaml_loads_without_errors() -> None:
    payload = yaml.safe_load(Path("brand/fsm.yaml").read_text(encoding="utf-8"))

    config = FSMConfig.model_validate(payload)

    assert config.initial_state == "idle"
    assert "greeting" in config.states


def test_invalid_target_in_fsm_yaml_raises_validation_error() -> None:
    payload = {
        "initial_state": "idle",
        "states": {
            "idle": {
                "description": "Idle state",
                "allowed_transitions": [
                    {
                        "target": "missing_state",
                        "event": "user_message",
                        "actions": [],
                    }
                ],
                "on_enter": [],
                "on_exit": [],
            }
        },
    }

    with pytest.raises(ValidationError) as exc_info:
        FSMConfig.model_validate(payload)

    assert "unknown transition target 'missing_state'" in str(exc_info.value)
