from core.services.handoff_service import _classify_handoff_state


def test_responded_state() -> None:
    ctx = {"advisor_responded": True, "current_state": "handoff_active"}
    assert _classify_handoff_state(ctx) == "responded"


def test_stop_by_opt_out() -> None:
    ctx = {"opt_out": True, "current_state": "handoff_active"}
    assert _classify_handoff_state(ctx) == "stop"


def test_stop_by_silenced() -> None:
    ctx = {"is_silenced": True, "current_state": "handoff_active"}
    assert _classify_handoff_state(ctx) == "stop"


def test_active_state() -> None:
    ctx = {"current_state": "handoff_active"}
    assert _classify_handoff_state(ctx) == "active"


def test_pending_state() -> None:
    ctx = {"current_state": "handoff_pending"}
    assert _classify_handoff_state(ctx) == "pending"


def test_interested_with_vehicle() -> None:
    ctx = {"current_state": "handoff_active", "vehicle_interest": "volteo"}
    assert _classify_handoff_state(ctx) == "interested"


def test_empty_context_returns_pending() -> None:
    assert _classify_handoff_state({}) == "pending"
