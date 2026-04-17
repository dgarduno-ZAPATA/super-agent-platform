from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class StrictEvolutionModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class EvolutionMessageKey(StrictEvolutionModel):
    remoteJid: str
    id: str
    fromMe: bool
    participant: str | None = None


class EvolutionExtendedTextMessage(StrictEvolutionModel):
    text: str


class EvolutionImageMessage(StrictEvolutionModel):
    caption: str | None = None
    url: str | None = None


class EvolutionAudioMessage(StrictEvolutionModel):
    url: str | None = None


class EvolutionDocumentMessage(StrictEvolutionModel):
    url: str | None = None
    fileName: str | None = None


class EvolutionVideoMessage(StrictEvolutionModel):
    caption: str | None = None
    url: str | None = None


class EvolutionLocationMessage(StrictEvolutionModel):
    degreesLatitude: float | None = None
    degreesLongitude: float | None = None
    name: str | None = None


class EvolutionStickerMessage(StrictEvolutionModel):
    url: str | None = None


class EvolutionContactMessage(StrictEvolutionModel):
    displayName: str | None = None


class EvolutionReactionMessage(StrictEvolutionModel):
    text: str | None = None


class EvolutionMessageContent(StrictEvolutionModel):
    conversation: str | None = None
    extendedTextMessage: EvolutionExtendedTextMessage | None = None
    imageMessage: EvolutionImageMessage | None = None
    audioMessage: EvolutionAudioMessage | None = None
    documentMessage: EvolutionDocumentMessage | None = None
    videoMessage: EvolutionVideoMessage | None = None
    locationMessage: EvolutionLocationMessage | None = None
    stickerMessage: EvolutionStickerMessage | None = None
    contactMessage: EvolutionContactMessage | None = None
    reactionMessage: EvolutionReactionMessage | None = None


class EvolutionMessagePayload(StrictEvolutionModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    key: EvolutionMessageKey
    messageType: str
    message: EvolutionMessageContent
    pushName: str | None = None
    messageTimestamp: int | str | None = None
    instanceId: str | None = None
    source: str | None = None


class EvolutionWebhookEnvelope(StrictEvolutionModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    event: str
    instance: str
    data: EvolutionMessagePayload | dict[str, Any]
