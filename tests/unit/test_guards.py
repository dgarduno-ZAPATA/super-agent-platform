from __future__ import annotations

from core.fsm.guards import (
    has_budget_guard,
    has_vehicle_interest_guard,
    user_requested_handoff_guard,
)


def test_handoff_guard_asesor() -> None:
    assert user_requested_handoff_guard({"inbound_text": "quiero hablar con un asesor"}) is True


def test_handoff_guard_false() -> None:
    assert user_requested_handoff_guard({"inbound_text": "busco un camión de volteo"}) is False


def test_handoff_guard_case_insensitive() -> None:
    assert user_requested_handoff_guard({"inbound_text": "COMUNÍCAME CON ALGUIEN"}) is True


def test_vehicle_interest_guard_true() -> None:
    assert has_vehicle_interest_guard({"vehicle_interest": "volteo"}) is True


def test_vehicle_interest_guard_legacy_key() -> None:
    assert has_vehicle_interest_guard({"vehiculo_interes": "tractocamion"}) is True


def test_vehicle_interest_guard_false() -> None:
    assert has_vehicle_interest_guard({}) is False


def test_budget_guard_true() -> None:
    assert has_budget_guard({"budget": 1_500_000.0}) is True


def test_budget_guard_false() -> None:
    assert has_budget_guard({"budget": None}) is False


def test_budget_guard_zero() -> None:
    assert has_budget_guard({"budget": 0}) is False
