"""PDF parsing and text chunking pipeline.
"""

import fitz  # PyMuPDF
import re
import logging

logger = logging.getLogger(__name__)

# ─── Chunking parameters ────────────────────────────────────────
MIN_CHUNK_LENGTH = 50       # Characters – ignore very short chunks
MAX_CHUNK_LENGTH = 1500     # Characters – split overly long chunks
OVERLAP_SENTENCES = 1       # Number of sentences to overlap between chunks


def extract_text_from_pdf(pdf_bytes: bytes) -> tuple[str, int]:
    """Extract all text from a PDF. Returns (full_text, page_count)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_count = len(doc)
    pages_text = []

    for page in doc:
        text = page.get_text("text")
        if text.strip():
            pages_text.append(text.strip())

    doc.close()
    full_text = "\n\n".join(pages_text)
    logger.info(f"Extracted {len(full_text)} chars from {page_count} pages")
    return full_text, page_count


def split_into_chunks(text: str) -> list[str]:
    """Split extracted text into retrieval-friendly paragraph chunks.

    Strategy:
    1. Split by double newlines (natural paragraph breaks).
    2. For very long paragraphs, further split by sentences.
    3. Filter out chunks that are too short to be useful.
    4. Add 1-sentence overlap between consecutive chunks for context.
    """
    # Step 1: Split on paragraph boundaries
    raw_paragraphs = re.split(r"\n{2,}", text)

    # Step 2: Process each paragraph
    chunks = []
    for para in raw_paragraphs:
        para = para.strip()
        para = re.sub(r"\s+", " ", para)  # Normalize whitespace

        if len(para) < MIN_CHUNK_LENGTH:
            continue

        if len(para) <= MAX_CHUNK_LENGTH:
            chunks.append(para)
        else:
            # Split long paragraphs by sentences
            sentences = _split_sentences(para)
            current_chunk = []
            current_len = 0

            for sentence in sentences:
                if current_len + len(sentence) > MAX_CHUNK_LENGTH and current_chunk:
                    chunks.append(" ".join(current_chunk))
                    # Overlap: keep last sentence
                    if OVERLAP_SENTENCES > 0 and len(current_chunk) >= OVERLAP_SENTENCES:
                        current_chunk = current_chunk[-OVERLAP_SENTENCES:]
                        current_len = sum(len(s) for s in current_chunk)
                    else:
                        current_chunk = []
                        current_len = 0

                current_chunk.append(sentence)
                current_len += len(sentence)

            if current_chunk:
                joined = " ".join(current_chunk)
                if len(joined) >= MIN_CHUNK_LENGTH:
                    chunks.append(joined)

    logger.info(f"Split text into {len(chunks)} chunks")
    return chunks


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using basic regex."""
    # Split on period/question/exclamation followed by space and uppercase letter
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [s.strip() for s in sentences if s.strip()]
