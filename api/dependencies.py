from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from adapters.branches.sheets_adapter import SheetsBranchAdapter
from adapters.crm.monday_adapter import MondayCRMAdapter
from adapters.inventory.sheets_adapter import SheetsInventoryAdapter
from adapters.knowledge.pgvector_adapter import PgVectorKnowledgeAdapter
from adapters.llm.openai_adapter import OpenAILLMAdapter
from adapters.llm.resilient_adapter import ResilientLLMAdapter
from adapters.llm.vertex_adapter import VertexLLMAdapter
from adapters.llm.vertex_embedding_adapter import VertexEmbeddingAdapter
from adapters.llm.vertex_transcription_adapter import VertexTranscriptionAdapter
from adapters.messaging.evolution.adapter import EvolutionMessagingAdapter
from adapters.storage.db import get_session_factory
from adapters.storage.repositories.admin_totp_repo import PostgresAdminTOTPRepository
from adapters.storage.repositories.audit_log_repo import PostgresAuditLogRepository
from adapters.storage.repositories.crm_outbox_repo import PostgresCRMOutboxRepository
from adapters.storage.repositories.event_repo import PostgresConversationEventRepository
from adapters.storage.repositories.knowledge_repo import PostgresKnowledgeRepository
from adapters.storage.repositories.lead_repo import PostgresLeadProfileRepository
from adapters.storage.repositories.login_attempt_repo import PostgresLoginAttemptRepository
from adapters.storage.repositories.outbound_queue_repo import PostgresOutboundQueueRepository
from adapters.storage.repositories.session_repo import PostgresSessionRepository
from adapters.storage.repositories.silenced_repo import PostgresSilencedUserRepository
from core.auth.jwt_handler import verify_token
from core.brand.schema import Brand
from core.config import get_settings
from core.fsm.schema import FSMConfig
from core.ports.branch_provider import BranchProvider
from core.ports.crm_provider import CRMProvider
from core.ports.inventory_provider import InventoryProvider
from core.ports.knowledge_provider import KnowledgeProvider
from core.ports.llm_provider import LLMProvider
from core.ports.messaging_provider import MessagingProvider
from core.ports.repositories import (
    ConversationEventRepository,
    CRMOutboxRepository,
    LeadProfileRepository,
    OutboundQueueRepository,
    SessionRepository,
    SilencedUserRepository,
)
from core.ports.transcription_provider import TranscriptionProvider
from core.services.audit_log_service import AuditLogService
from core.services.campaign_worker import CampaignWorker
from core.services.conversation_agent import ConversationAgent
from core.services.dashboard_service import DashboardService
from core.services.document_chunker import DocumentChunker
from core.services.handoff_service import HandoffService
from core.services.image_analysis_service import ImageAnalysisService
from core.services.inbound_handler import InboundMessageHandler
from core.services.knowledge_ingestion_service import KnowledgeIngestionService
from core.services.login_attempt_service import LoginAttemptService
from core.services.orchestrator import OrchestratorAgent
from core.services.replay_engine import ReplayEngine
from core.services.skills import SkillRegistry


def get_brand(request: Request) -> Brand:
    return request.app.state.brand


def get_current_user(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> dict[str, object]:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_authorization_header",
        )
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_authorization_scheme",
        )
    token = authorization[7:].strip()
    return verify_token(token)


def get_current_user_or_none(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> dict[str, object] | None:
    if not authorization:
        return None
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_authorization_scheme",
        )
    token = authorization[7:].strip()
    return verify_token(token)


def require_internal_or_user(
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
    current_user: Annotated[dict[str, object] | None, Depends(get_current_user_or_none)] = None,
) -> dict[str, object]:
    settings = get_settings()
    if x_internal_token and x_internal_token == settings.internal_token:
        return {"auth_type": "internal_token"}
    if current_user is not None:
        return current_user
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="missing_credentials",
    )


def get_messaging_provider() -> MessagingProvider:
    return EvolutionMessagingAdapter(get_settings())


def get_crm_provider() -> CRMProvider:
    return MondayCRMAdapter()


def get_branch_provider() -> BranchProvider:
    settings = get_settings()
    return SheetsBranchAdapter(
        csv_url=settings.branch_sheet_url,
        cache_ttl_seconds=settings.branch_cache_ttl_seconds,
    )


def get_inventory_provider(
    brand: Annotated[Brand, Depends(get_brand)],
) -> InventoryProvider:
    settings = get_settings()
    csv_url = settings.inventory_sheet_url if settings.inventory_sheet_url.strip() else None
    return SheetsInventoryAdapter(
        csv_url=csv_url,
        inventory_columns=brand.brand.inventory_columns,
        fallback_products=brand.products.products,
        cache_ttl_seconds=settings.inventory_cache_ttl_seconds,
    )


def get_llm_provider() -> LLMProvider:
    primary = get_vertex_llm_adapter()
    settings = get_settings()
    fallback = OpenAILLMAdapter(
        api_key=settings.openai_api_key,
        model_name=settings.openai_model_name,
    )
    return ResilientLLMAdapter(primary=primary, fallback=fallback)


def get_vertex_llm_adapter() -> VertexLLMAdapter:
    settings = get_settings()
    return VertexLLMAdapter(
        project_id=settings.gcp_project_id,
        region=settings.gcp_region,
        model_name=settings.vertex_model_name,
        embedding_model_name=settings.vertex_embedding_model_name,
    )


async def get_knowledge_provider(
    llm_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> KnowledgeProvider:
    settings = get_settings()
    return PgVectorKnowledgeAdapter(
        llm_provider=llm_provider,
        embedding_adapter=VertexEmbeddingAdapter(
            project_id=settings.gcp_project_id,
            region=settings.gcp_region,
            model_name=settings.vertex_embedding_model_name,
        ),
        session_factory=await get_session_factory(),
    )


def get_knowledge_repository() -> PostgresKnowledgeRepository:
    return PostgresKnowledgeRepository()


def get_audit_log_repository() -> PostgresAuditLogRepository:
    return PostgresAuditLogRepository()


def get_audit_log_service(
    audit_log_repository: Annotated[PostgresAuditLogRepository, Depends(get_audit_log_repository)],
) -> AuditLogService:
    return AuditLogService(repo=audit_log_repository)


def get_login_attempt_repository() -> PostgresLoginAttemptRepository:
    return PostgresLoginAttemptRepository()


def get_login_attempt_service(
    login_attempt_repository: Annotated[
        PostgresLoginAttemptRepository, Depends(get_login_attempt_repository)
    ],
) -> LoginAttemptService:
    return LoginAttemptService(repo=login_attempt_repository)


def get_admin_totp_repository() -> PostgresAdminTOTPRepository:
    return PostgresAdminTOTPRepository()


def get_knowledge_ingestion_service() -> KnowledgeIngestionService:
    settings = get_settings()
    embedding_adapter = VertexEmbeddingAdapter(
        project_id=settings.gcp_project_id,
        region=settings.gcp_region,
        model_name=settings.vertex_embedding_model_name,
    )
    return KnowledgeIngestionService(
        chunker=DocumentChunker(),
        embedding_adapter=embedding_adapter,
        knowledge_repo=get_knowledge_repository(),
    )


def get_transcription_provider() -> TranscriptionProvider:
    return VertexTranscriptionAdapter(vertex_adapter=get_vertex_llm_adapter())


def get_image_analysis_service() -> ImageAnalysisService:
    return ImageAnalysisService(vertex_adapter=get_vertex_llm_adapter())


def get_conversation_event_repository() -> ConversationEventRepository:
    return PostgresConversationEventRepository()


def get_crm_outbox_repository() -> CRMOutboxRepository:
    return PostgresCRMOutboxRepository()


def get_lead_profile_repository() -> LeadProfileRepository:
    return PostgresLeadProfileRepository()


def get_session_repository() -> SessionRepository:
    return PostgresSessionRepository()


def get_outbound_queue_repository() -> OutboundQueueRepository:
    return PostgresOutboundQueueRepository()


def get_handoff_service(
    session_repository: Annotated[SessionRepository, Depends(get_session_repository)],
    conversation_event_repository: Annotated[
        ConversationEventRepository, Depends(get_conversation_event_repository)
    ],
) -> HandoffService:
    return HandoffService(
        session_repository=session_repository,
        conversation_event_repository=conversation_event_repository,
    )


def get_dashboard_service(
    session_repository: Annotated[SessionRepository, Depends(get_session_repository)],
    lead_profile_repository: Annotated[LeadProfileRepository, Depends(get_lead_profile_repository)],
    conversation_event_repository: Annotated[
        ConversationEventRepository, Depends(get_conversation_event_repository)
    ],
    outbound_queue_repository: Annotated[
        OutboundQueueRepository, Depends(get_outbound_queue_repository)
    ],
    crm_outbox_repository: Annotated[CRMOutboxRepository, Depends(get_crm_outbox_repository)],
) -> DashboardService:
    return DashboardService(
        session_repository=session_repository,
        lead_profile_repository=lead_profile_repository,
        conversation_event_repository=conversation_event_repository,
        outbound_queue_repository=outbound_queue_repository,
        crm_outbox_repository=crm_outbox_repository,
    )


def get_campaign_worker(
    outbound_queue_repository: Annotated[
        OutboundQueueRepository, Depends(get_outbound_queue_repository)
    ],
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
) -> CampaignWorker:
    settings = get_settings()
    return CampaignWorker(
        outbound_queue_repository=outbound_queue_repository,
        messaging_provider=messaging_provider,
        batch_size=settings.campaign_batch_size,
        rate_limit_ms=settings.campaign_rate_limit_ms,
    )


def get_replay_engine(
    brand: Annotated[Brand, Depends(get_brand)],
    lead_profile_repository: Annotated[LeadProfileRepository, Depends(get_lead_profile_repository)],
    session_repository: Annotated[SessionRepository, Depends(get_session_repository)],
    conversation_event_repository: Annotated[
        ConversationEventRepository, Depends(get_conversation_event_repository)
    ],
) -> ReplayEngine:
    return ReplayEngine(
        lead_profile_repository=lead_profile_repository,
        session_repository=session_repository,
        event_repository=conversation_event_repository,
        fsm_config=brand.fsm,
        handoff_keywords=brand.policies.handoff_keywords,
        opt_out_keywords=brand.policies.opt_out_keywords,
    )


def get_silenced_user_repository() -> SilencedUserRepository:
    return PostgresSilencedUserRepository()


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


async def get_skill_registry(
    knowledge_provider: Annotated[KnowledgeProvider, Depends(get_knowledge_provider)],
    inventory_provider: Annotated[InventoryProvider, Depends(get_inventory_provider)],
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
    brand: Annotated[Brand, Depends(get_brand)],
) -> SkillRegistry:
    return SkillRegistry(
        knowledge_provider=knowledge_provider,
        inventory_provider=inventory_provider,
        messaging_provider=messaging_provider,
        brand=brand,
    )


def get_conversation_agent(
    llm_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
    brand: Annotated[Brand, Depends(get_brand)],
    conversation_event_repository: Annotated[
        ConversationEventRepository, Depends(get_conversation_event_repository)
    ],
    skill_registry: Annotated[SkillRegistry, Depends(get_skill_registry)],
) -> ConversationAgent:
    return ConversationAgent(
        llm_provider=llm_provider,
        messaging_provider=messaging_provider,
        brand=brand,
        conversation_event_repository=conversation_event_repository,
        skill_registry=skill_registry,
    )


def get_inbound_message_handler(
    messaging_provider: Annotated[MessagingProvider, Depends(get_messaging_provider)],
    conversation_event_repository: Annotated[
        ConversationEventRepository, Depends(get_conversation_event_repository)
    ],
    lead_profile_repository: Annotated[LeadProfileRepository, Depends(get_lead_profile_repository)],
    crm_outbox_repository: Annotated[CRMOutboxRepository, Depends(get_crm_outbox_repository)],
    session_repository: Annotated[SessionRepository, Depends(get_session_repository)],
    silenced_user_repository: Annotated[
        SilencedUserRepository, Depends(get_silenced_user_repository)
    ],
    transcription_provider: Annotated[TranscriptionProvider, Depends(get_transcription_provider)],
    image_analysis_service: Annotated[ImageAnalysisService, Depends(get_image_analysis_service)],
    conversation_agent: Annotated[ConversationAgent, Depends(get_conversation_agent)],
    orchestrator: Annotated[OrchestratorAgent, Depends(get_orchestrator_agent)],
    fsm_config: Annotated[FSMConfig, Depends(get_fsm_config)],
    branch_provider: Annotated[BranchProvider, Depends(get_branch_provider)],
    brand: Annotated[Brand, Depends(get_brand)],
) -> InboundMessageHandler:
    return InboundMessageHandler(
        messaging_provider=messaging_provider,
        conversation_event_repository=conversation_event_repository,
        lead_profile_repository=lead_profile_repository,
        crm_outbox_repository=crm_outbox_repository,
        session_repository=session_repository,
        silenced_user_repository=silenced_user_repository,
        transcription_provider=transcription_provider,
        image_analysis_service=image_analysis_service,
        conversation_agent=conversation_agent,
        orchestrator=orchestrator,
        fsm_config=fsm_config,
        branch_provider=branch_provider,
        brand=brand,
    )
