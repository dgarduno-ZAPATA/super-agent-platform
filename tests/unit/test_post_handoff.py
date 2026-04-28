from __future__ import annotations

from core.services.conversation_agent import should_send_handoff_message


def test_handoff_pending_first_message() -> None:
    assert should_send_handoff_message("handoff_pending", []) is True


def test_handoff_active_first_message() -> None:
    assert should_send_handoff_message("handoff_active", []) is True


def test_handoff_already_sent_silence() -> None:
    prev = ["Ya le avisé a un asesor, en breve te atiende."]
    assert should_send_handoff_message("handoff_pending", prev) is False


def test_non_handoff_state_not_affected() -> None:
    assert should_send_handoff_message("catalog_navigation", []) is False


def test_handoff_other_bot_messages_not_silence() -> None:
    prev = ["Hola, soy Raúl.", "Tenemos camiones disponibles."]
    assert should_send_handoff_message("handoff_active", prev) is True
