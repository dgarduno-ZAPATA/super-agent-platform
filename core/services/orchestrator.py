from __future__ import annotations

import re

from core.brand.schema import Brand
from core.domain.classification import MessageClassification
from core.domain.messaging import InboundEvent, MessageKind
from core.domain.session import Session
from core.fsm.schema import FSMConfig
from core.ports.repositories import SilencedUserRepository


class OrchestratorAgent:
    def __init__(
        self,
        brand: Brand,
        fsm_config: FSMConfig,
        silenced_user_repository: SilencedUserRepository,
    ) -> None:
        self._brand = brand
        self._fsm_config = fsm_config
        self._silenced_user_repository = silenced_user_repository
        self._opt_out_keywords = [
            keyword.lower().strip() for keyword in brand.policies.opt_out_keywords
        ]
        self._handoff_keywords = [
            keyword.lower().strip() for keyword in brand.policies.handoff_keywords
        ]

    async def classify(self, event: InboundEvent, session: Session) -> MessageClassification:
        if event.kind is MessageKind.UNSUPPORTED:
            return MessageClassification(
                intent="unsupported",
                confidence=1.0,
                fsm_event="user_message",
                metadata={"reason": "unsupported_message_kind"},
            )

        normalized_text = (event.text or "").lower().strip()
        matched_opt_out = self._match_keyword(normalized_text, self._opt_out_keywords)
        if matched_opt_out is not None:
            return MessageClassification(
                intent="opt_out",
                confidence=1.0,
                fsm_event="opt_out_detected",
                metadata={"matched_keyword": matched_opt_out},
            )

        matched_handoff = self._match_keyword(normalized_text, self._handoff_keywords)
        if matched_handoff is not None:
            handoff_response_text = self._brand.policies.handoff_response_text.format(
                brand_name=self._brand.brand.display_name
            )
            return MessageClassification(
                intent="handoff_request",
                confidence=1.0,
                fsm_event="handoff_requested",
                metadata={
                    "matched_keyword": matched_handoff,
                    "handoff_response_text": handoff_response_text,
                },
            )

        campaign_id = session.context.get("campaign_id")
        if (
            session.current_state in {"outbound_sent", "idle"}
            and isinstance(campaign_id, str)
            and campaign_id.strip()
        ):
            return MessageClassification(
                intent="campaign_reply",
                confidence=0.8,
                fsm_event="campaign_reply_received",
                metadata={"campaign_id": campaign_id},
            )

        return MessageClassification(
            intent="conversation",
            confidence=0.8,
            fsm_event="user_message",
            metadata={},
        )

    @staticmethod
    def _match_keyword(text: str, keywords: list[str]) -> str | None:
        if not text:
            return None

        for keyword in keywords:
            if not keyword:
                continue

            pattern = re.compile(rf"(?<!\w){re.escape(keyword)}(?!\w)", flags=re.IGNORECASE)
            if pattern.search(text):
                return keyword

        return None
