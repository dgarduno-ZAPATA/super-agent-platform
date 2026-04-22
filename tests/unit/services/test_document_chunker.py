from core.services.document_chunker import DocumentChunker


def test_chunker_respects_size_and_overlap() -> None:
    chunker = DocumentChunker()
    text = "A" * 2000
    chunks = chunker.chunk_text(text, chunk_size=800, overlap=150, source_name="test-source")

    assert chunks
    assert all(len(str(chunk["text"])) <= 800 for chunk in chunks)
    for index in range(1, len(chunks)):
        prev = str(chunks[index - 1]["text"])
        curr = str(chunks[index]["text"])
        assert prev[-150:] == curr[:150]


def test_chunk_markdown_preserves_section_content() -> None:
    chunker = DocumentChunker()
    markdown = "# Titulo\nDetalle del catalogo\n\n## Seccion\nMas contenido tecnico"
    chunks = chunker.chunk_markdown(markdown, source_name="md-source")

    assert chunks
    text_blob = " ".join(str(chunk["text"]) for chunk in chunks)
    assert "Detalle del catalogo" in text_blob
    assert "Mas contenido tecnico" in text_blob
