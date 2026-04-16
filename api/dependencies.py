from typing import Annotated

from fastapi import Depends, Request

from adapters.messaging.evolution.adapter import EvolutionMessagingAdapter
from adapters.storage.repositories.event_repo import PostgresConversationEventRepository
from adapters.storage.repositories.lead_repo import PostgresLeadProfileRepository
from adapters.storage.repositories.session_repo import PostgresSessionRepository
from adapters.storage.repositories.silenced_repo import PostgresSilencedUserRepository
from adapters.transcription.whisper_stub import WhisperStubTranscriptionProvider
from core.brand.schema import Brand
from core.config import get_settings
from core.ports.messaging_provider import MessagingProvider
from core.ports.repositories import (
    ConversationEventRepository,
    LeadProfileRepository,
    SessionRepository,
    SilencedUserRepository,
)
from core.ports.transcription_provider import TranscriptionProvider
from core.services.inbound_handler import InboundMessageHandler
from core.services.responder import EchoResponder


def get_messaging_provider() -> MessagingProvider:
    return EvolutionMessagingAdapter(get_settings())


def get_transcription_provider() -> TranscriptionProvider:
    return WhisperStubTranscriptionProvider()


def get_conversation_event_repository() -> ConversationEventRepository:
    return PostgresConversationEventRepository()


def get_lead_profile_repository() -> LeadProfileRepository:
    return PostgresLeadProfileRepository()


def get_session_repository() -> SessionRepository:
    return PostgresSessionRepository()


def get_silenced_user_repository() -> SilencedUserRepository:
    return PostgresSilencedUserRepository()


def get_brand(request: Request) -> Brand:
    return request.app.state.brand


def get_echo_responder(
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
    brand: Annotated[Brand, Depends(get_brand)],
) -> EchoResponder:
    return EchoResponder(messaging_provider=messaging_provider, brand=brand)


def get_inbound_message_handler(
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
    conversation_event_repository: Annotated[
        ConversationEventRepository, Depends(get_conversation_event_repository)
    ],
    lead_profile_repository: Annotated[LeadProfileRepository, Depends(get_lead_profile_repository)],
    session_repository: Annotated[SessionRepository, Depends(get_session_repository)],
    silenced_user_repository: Annotated[
        SilencedUserRepository, Depends(get_silenced_user_repository)
    ],
    transcription_provider: Annotated[TranscriptionProvider, Depends(get_transcription_provider)],
    responder: Annotated[EchoResponder, Depends(get_echo_responder)],
) -> InboundMessageHandler:
    return InboundMessageHandler(
        messaging_provider=messaging_provider,
        conversation_event_repository=conversation_event_repository,
        lead_profile_repository=lead_profile_repository,
        session_repository=session_repository,
        silenced_user_repository=silenced_user_repository,
        transcription_provider=transcription_provider,
        responder=responder,
    )
