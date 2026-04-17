from typing import Annotated

from fastapi import Depends, Request

from adapters.llm.vertex_adapter import VertexLLMAdapter
from adapters.messaging.evolution.adapter import EvolutionMessagingAdapter
from adapters.storage.repositories.event_repo import PostgresConversationEventRepository
from adapters.storage.repositories.lead_repo import PostgresLeadProfileRepository
from adapters.storage.repositories.session_repo import PostgresSessionRepository
from adapters.storage.repositories.silenced_repo import PostgresSilencedUserRepository
from adapters.transcription.whisper_stub import WhisperStubTranscriptionProvider
from core.brand.schema import Brand
from core.config import get_settings
from core.fsm.schema import FSMConfig
from core.ports.llm_provider import LLMProvider
from core.ports.messaging_provider import MessagingProvider
from core.ports.repositories import (
    ConversationEventRepository,
    LeadProfileRepository,
    SessionRepository,
    SilencedUserRepository,
)
from core.ports.transcription_provider import TranscriptionProvider
from core.services.conversation_agent import ConversationAgent
from core.services.inbound_handler import InboundMessageHandler
from core.services.orchestrator import OrchestratorAgent


def get_messaging_provider() -> MessagingProvider:
    return EvolutionMessagingAdapter(get_settings())


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    return VertexLLMAdapter(
        project_id=settings.gcp_project_id,
        region=settings.gcp_region,
        model_name=settings.vertex_model_name,
    )


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


def get_fsm_config(brand: Annotated[Brand, Depends(get_brand)]) -> FSMConfig:
    return brand.fsm


def get_orchestrator_agent(
    brand: Annotated[Brand, Depends(get_brand)],
    fsm_config: Annotated[FSMConfig, Depends(get_fsm_config)],
    silenced_user_repository: Annotated[
        SilencedUserRepository, Depends(get_silenced_user_repository)
    ],
) -> OrchestratorAgent:
    return OrchestratorAgent(
        brand=brand,
        fsm_config=fsm_config,
        silenced_user_repository=silenced_user_repository,
    )


def get_conversation_agent(
    llm_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
    brand: Annotated[Brand, Depends(get_brand)],
    conversation_event_repository: Annotated[
        ConversationEventRepository, Depends(get_conversation_event_repository)
    ],
) -> ConversationAgent:
    return ConversationAgent(
        llm_provider=llm_provider,
        messaging_provider=messaging_provider,
        brand=brand,
        conversation_event_repository=conversation_event_repository,
    )


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
    conversation_agent: Annotated[ConversationAgent, Depends(get_conversation_agent)],
    orchestrator: Annotated[OrchestratorAgent, Depends(get_orchestrator_agent)],
    fsm_config: Annotated[FSMConfig, Depends(get_fsm_config)],
) -> InboundMessageHandler:
    return InboundMessageHandler(
        messaging_provider=messaging_provider,
        conversation_event_repository=conversation_event_repository,
        lead_profile_repository=lead_profile_repository,
        session_repository=session_repository,
        silenced_user_repository=silenced_user_repository,
        transcription_provider=transcription_provider,
        conversation_agent=conversation_agent,
        orchestrator=orchestrator,
        fsm_config=fsm_config,
    )
