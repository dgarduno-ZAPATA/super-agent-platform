from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog

ActionFunction = Callable[[dict[str, object]], Awaitable[None]]
ActionRegistry = dict[str, ActionFunction]

logger = structlog.get_logger("super_agent_platform.core.fsm.actions")


async def log_transition_action(context: dict[str, object]) -> None:
    logger.info(
        "fsm_transition_action",
        event=context.get("event"),
        old_state=context.get("old_state"),
        new_state=context.get("new_state"),
        guard=context.get("guard"),
    )


async def update_session_action(context: dict[str, object]) -> None:
    logger.info(
        "fsm_update_session_stub",
        state=context.get("new_state") or context.get("current_state"),
    )


async def update_crm_stage_action(context: dict[str, object]) -> None:
    stage = context.get("stage") or context.get("new_state")
    logger.info("fsm_update_crm_stage_stub", message=f"CRM stage update: {stage}")


async def notify_agent_action(context: dict[str, object]) -> None:
    del context
    logger.info(
        "fsm_notify_agent_stub",
        message="Agent notification: handoff requested",
    )


async def send_document_action(context: dict[str, object]) -> None:
    del context
    logger.info("fsm_send_document_stub", message="Document sent")


def build_default_action_registry() -> ActionRegistry:
    return {
        "log_transition": log_transition_action,
        "update_session": update_session_action,
        "update_crm_stage": update_crm_stage_action,
        "notify_agent": notify_agent_action,
        "send_document": send_document_action,
    }
