from __future__ import annotations

from core.services.friction_detector import _has_friction_keyword, detect_friction


def test_friction_keyword_detected() -> None:
    assert _has_friction_keyword("ya te dije lo que busco") is True


def test_no_friction_keyword() -> None:
    assert _has_friction_keyword("busco un camión de volteo") is False


def test_stale_state_triggers_friction() -> None:
    assert (
        detect_friction(
            current_client_message="¿qué tienes?",
            recent_client_messages=["hola", "qué opciones hay"],
            current_state="catalog_navigation",
            recent_states=[
                "catalog_navigation",
                "catalog_navigation",
                "catalog_navigation",
            ],
        )
        is True
    )


def test_stale_state_below_threshold_no_friction() -> None:
    assert (
        detect_friction(
            current_client_message="¿qué tienes?",
            recent_client_messages=["hola"],
            current_state="catalog_navigation",
            recent_states=["catalog_navigation", "catalog_navigation"],
        )
        is False
    )


def test_different_states_no_stale_friction() -> None:
    assert (
        detect_friction(
            current_client_message="ok",
            recent_client_messages=["busco volteo", "soy Diego"],
            current_state="qualification",
            recent_states=["greeting", "discovery", "catalog_navigation"],
        )
        is False
    )


def test_keyword_threshold_triggers_friction() -> None:
    assert (
        detect_friction(
            current_client_message="no me entiendes",
            recent_client_messages=["ya te dije lo que busco"],
            current_state="discovery",
            recent_states=["discovery"],
        )
        is True
    )


def test_single_keyword_no_friction() -> None:
    assert (
        detect_friction(
            current_client_message="no entiendo",
            recent_client_messages=["busco un camión"],
            current_state="discovery",
            recent_states=["discovery"],
        )
        is False
    )


def test_empty_history_no_friction() -> None:
    assert (
        detect_friction(
            current_client_message="hola",
            recent_client_messages=[],
            current_state="greeting",
            recent_states=[],
        )
        is False
    )
