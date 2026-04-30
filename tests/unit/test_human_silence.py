from __future__ import annotations

from core.services.inbound_handler import _is_human_advisor_message


def test_client_message_not_advisor() -> None:
    assert (
        _is_human_advisor_message(
            from_me=False,
            message_id="any-id",
            is_in_bot_cache=False,
        )
        is False
    )


def test_bot_own_message_not_advisor() -> None:
    assert (
        _is_human_advisor_message(
            from_me=True,
            message_id="bot-msg-001",
            is_in_bot_cache=True,
        )
        is False
    )


def test_human_advisor_message_detected() -> None:
    assert (
        _is_human_advisor_message(
            from_me=True,
            message_id="human-msg-001",
            is_in_bot_cache=False,
        )
        is True
    )


def test_from_me_false_ignores_cache() -> None:
    assert (
        _is_human_advisor_message(
            from_me=False,
            message_id="unknown",
            is_in_bot_cache=False,
        )
        is False
    )


def test_from_me_true_in_cache_is_bot() -> None:
    assert (
        _is_human_advisor_message(
            from_me=True,
            message_id="bot-reflected",
            is_in_bot_cache=True,
        )
        is False
    )
