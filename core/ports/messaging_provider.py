from typing import Protocol

from core.domain.messaging import InboundEvent, MessageDeliveryReceipt


class MessagingProvider(Protocol):
    async def send_text(self, to: str, text: str, correlation_id: str) -> MessageDeliveryReceipt:
        """Send plain text to a recipient and return a canonical delivery receipt."""

    async def send_image(
        self, to: str, image_url: str, caption: str | None, correlation_id: str
    ) -> MessageDeliveryReceipt:
        """Send an image, optionally with caption text, and return a canonical delivery receipt."""

    async def send_document(
        self, to: str, document_url: str, filename: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        """Send a document with its business filename and return a canonical delivery receipt."""

    async def send_audio(
        self, to: str, audio_url: str, correlation_id: str
    ) -> MessageDeliveryReceipt:
        """Send an audio asset to a recipient and return a canonical delivery receipt."""

    async def mark_read(self, message_id: str) -> None:
        """Mark a previously seen inbound message as read in the underlying channel."""

    async def get_media_base64(
        self,
        message_id: str,
        sender_id: str,
        from_me: bool = False,
    ) -> str | None: ...

    @staticmethod
    def parse_inbound_event(raw_payload: dict[str, object]) -> InboundEvent:
        """Normalize a provider webhook payload into the canonical inbound event shape."""
