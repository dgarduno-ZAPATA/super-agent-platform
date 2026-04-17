from core.fsm.guards import build_default_guard_registry


def test_default_guards_behave_as_expected() -> None:
    guards = build_default_guard_registry()

    assert guards["always"]({}) is True
    assert guards["has_phone_number"]({"phone": "5214421234567"}) is True
    assert guards["has_phone_number"]({}) is False
    assert guards["is_not_silenced"]({"is_silenced": False}) is True
    assert guards["is_not_silenced"]({"is_silenced": True}) is False
    assert guards["opt_out_detected"]({"opt_out_detected": True}) is True
    assert guards["opt_out_detected"]({}) is False
    assert guards["has_name"]({"name": "Estefania"}) is True
    assert guards["has_name"]({}) is False
