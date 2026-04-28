from __future__ import annotations

from core.services.conversation_agent import should_send_handoff_message

HANDOFF_WAITING = "Ya le avise a un asesor, en breve te atiende."


def test_handoff_pending_first_message() -> None:
    assert should_send_handoff_message("handoff_pending", [], HANDOFF_WAITING) is True


def test_handoff_active_first_message() -> None:
    assert should_send_handoff_message("handoff_active", [], HANDOFF_WAITING) is True


def test_handoff_already_sent_silence() -> None:
    prev = [HANDOFF_WAITING]
    assert should_send_handoff_message("handoff_pending", prev, HANDOFF_WAITING) is False


def test_non_handoff_state_not_affected() -> None:
    assert should_send_handoff_message("catalog_navigation", [], HANDOFF_WAITING) is False


def test_handoff_other_bot_messages_not_silence() -> None:
    prev = ["Hola, soy Raul.", "Tenemos camiones disponibles."]
    assert should_send_handoff_message("handoff_active", prev, HANDOFF_WAITING) is True
