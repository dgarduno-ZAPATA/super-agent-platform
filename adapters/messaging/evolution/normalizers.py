from __future__ import annotations

import re

from adapters.messaging.evolution.payloads import EvolutionMessagePayload
from core.domain.messaging import MessageKind

_KNOWN_MESSAGE_TYPES: dict[str, MessageKind] = {
    "conversation": MessageKind.TEXT,
    "extendedTextMessage": MessageKind.TEXT,
    "imageMessage": MessageKind.IMAGE,
    "audioMessage": MessageKind.AUDIO,
    "pttMessage": MessageKind.AUDIO,
    "ptt": MessageKind.AUDIO,
    "documentMessage": MessageKind.DOCUMENT,
    "videoMessage": MessageKind.VIDEO,
    "stickerMessage": MessageKind.UNSUPPORTED,
    "locationMessage": MessageKind.UNSUPPORTED,
    "contactMessage": MessageKind.UNSUPPORTED,
    "reactionMessage": MessageKind.UNSUPPORTED,
}


def normalize_phone(jid: str) -> str | None:
    if jid.endswith("@g.us"):
        return None

    local_part = jid.split("@", maxsplit=1)[0]
    digits = re.sub(r"\D", "", local_part)
    if not digits:
        return None

    if len(digits) < 8 or len(digits) > 15:
        return None

    return digits


def normalize_message_type(evolution_type: str) -> MessageKind:
    return _KNOWN_MESSAGE_TYPES.get(evolution_type, MessageKind.UNSUPPORTED)


def extract_text(payload: EvolutionMessagePayload) -> str | None:
    message = payload.message

    if message.conversation:
        return message.conversation
    if message.extendedTextMessage is not None:
        return message.extendedTextMessage.text
    if message.imageMessage is not None:
        return message.imageMessage.caption
    if message.videoMessage is not None:
        return message.videoMessage.caption
    if message.reactionMessage is not None:
        return message.reactionMessage.text

    return None
