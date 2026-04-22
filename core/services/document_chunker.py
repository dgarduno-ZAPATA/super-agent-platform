from __future__ import annotations

import io
import re

from docx import Document
from pypdf import PdfReader


class DocumentChunker:
    """Divide documentos en chunks con ventana deslizante y overlap."""

    def chunk_text(
        self,
        text: str,
        chunk_size: int = 800,
        overlap: int = 150,
        source_name: str = "",
    ) -> list[dict[str, object]]:
        normalized = self._normalize_text(text)
        if not normalized:
            return []

        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(start + chunk_size, len(normalized))
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(normalized):
                break
            start = max(end - overlap, 0)

        total = len(chunks)
        return [
            {
                "text": chunk,
                "source": source_name,
                "chunk_index": index,
                "total_chunks": total,
            }
            for index, chunk in enumerate(chunks)
        ]

    def chunk_pdf(self, pdf_bytes: bytes, source_name: str) -> list[dict[str, object]]:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages_text = [page.extract_text() or "" for page in reader.pages]
        return self.chunk_text("\n".join(pages_text), source_name=source_name)

    def chunk_markdown(self, md_text: str, source_name: str) -> list[dict[str, object]]:
        sections = re.split(r"\n(?=#{1,6}\s)", md_text)
        all_chunks: list[dict[str, object]] = []
        for section in sections:
            all_chunks.extend(self.chunk_text(section, source_name=source_name))
        total = len(all_chunks)
        for index, item in enumerate(all_chunks):
            item["chunk_index"] = index
            item["total_chunks"] = total
        return all_chunks

    def chunk_plain_text(self, text: str, source_name: str) -> list[dict[str, object]]:
        return self.chunk_text(text, source_name=source_name)

    def chunk_docx(self, file_bytes: bytes, source_name: str) -> list[dict[str, object]]:
        document = Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in document.paragraphs if p.text and p.text.strip()]
        return self.chunk_text("\n".join(paragraphs), source_name=source_name)

    @staticmethod
    def _normalize_text(text: str) -> str:
        collapsed = re.sub(r"\r\n?", "\n", text)
        collapsed = re.sub(r"[ \t]+", " ", collapsed)
        collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
        return collapsed.strip()
