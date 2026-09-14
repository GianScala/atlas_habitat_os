"""Cutting a document into passages small enough to retrieve.

A whole procedure document is too big to hand a model, and a single sentence is
too small to mean anything. Chunks are cut at paragraph boundaries where they
can be, so a step of a procedure or a row of a contact table stays intact, and
they overlap slightly so an answer that straddles a boundary is still findable
from either side.

Nothing here is clever. It does not need to be: the documents are procedures and
checklists, and keeping paragraphs whole gets most of the value.
"""

import re

# Characters, not tokens. Tokens would be more precise and would need the
# model's tokeniser to compute; at this size the difference does not change
# which passage comes back.
TARGET = 1200
OVERLAP = 150
MIN_CHUNK = 60

_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")

# A line that introduces a section rather than continuing one: a Markdown
# heading, a numbered clause, or a short line ending in a colon. Procedures are
# written in sections, and a passage that starts at one is far more useful than
# one that starts mid-sentence three lines above it.
_HEADING = re.compile(
    r"^(#{1,6}\s+\S|\d+(\.\d+)*[.)]\s+\S|[A-Z][A-Za-z0-9 /&'-]{0,60}:\s*$)"
)


def normalise(text: str) -> str:
    """Tidy whitespace without destroying paragraph structure."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE.sub(" ", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


def split(text: str) -> list[str]:
    """A document as overlapping passages, longest-coherent-unit first."""
    text = normalise(text)
    if not text:
        return []

    chunks: list[str] = []
    current = ""

    for paragraph in _sections(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        # A paragraph that is itself too long is split on sentences rather than
        # being truncated: a five-page section is still worth retrieving from.
        if len(paragraph) > TARGET:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long(paragraph))
            continue

        # A section that opens with a heading starts a new passage, even when
        # the previous one had room. Merging across a heading is what collapses
        # a short procedure document into a single undifferentiated blob.
        opens_section = bool(_HEADING.match(paragraph.split("\n", 1)[0].strip()))

        if not current:
            current = paragraph
        elif not opens_section and len(current) + len(paragraph) + 2 <= TARGET:
            current = f"{current}\n\n{paragraph}"
        else:
            chunks.append(current)
            current = paragraph

    if current:
        chunks.append(current)

    return _with_overlap([c for c in chunks if len(c.strip()) >= MIN_CHUNK])


def _sections(text: str) -> list[str]:
    """Paragraphs, further split wherever a heading starts a new section.

    Without this a short procedure document collapses into one passage and
    retrieval can only ever return the whole thing, which tells the model
    nothing about which part answered the question.
    """
    out: list[str] = []
    for paragraph in text.split("\n\n"):
        lines = paragraph.split("\n")
        buffer: list[str] = []
        for line in lines:
            if _HEADING.match(line.strip()) and buffer:
                out.append("\n".join(buffer).strip())
                buffer = [line]
            else:
                buffer.append(line)
        if buffer:
            out.append("\n".join(buffer).strip())
    return [section for section in out if section]


def _split_long(paragraph: str) -> list[str]:
    """One oversized paragraph, cut on sentence ends where possible."""
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    out: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= TARGET:
            current = f"{current} {sentence}".strip()
            continue
        if current:
            out.append(current)
        # A single sentence longer than a whole chunk gets hard-cut; there is
        # nothing else to cut it on.
        while len(sentence) > TARGET:
            out.append(sentence[:TARGET])
            sentence = sentence[TARGET:]
        current = sentence
    if current:
        out.append(current)
    return out


# Marks the borrowed tail of the previous passage. Kept visible so a reader can
# see where the carried-over context ends.
OVERLAP_MARK = "…"


def core_text(chunk: str) -> str:
    """A passage without the tail carried over from the one before it.

    Matching must score a passage on what it actually says. Scoring the borrowed
    prefix too makes every chunk look like its predecessor and pulls the wrong
    section back.
    """
    if chunk.startswith(OVERLAP_MARK) and "\n\n" in chunk:
        return chunk.split("\n\n", 1)[1]
    return chunk


def _with_overlap(chunks: list[str]) -> list[str]:
    """Carry the tail of each chunk into the next.

    A limit stated at the end of one passage and applied at the start of the
    next is otherwise findable from neither.
    """
    if len(chunks) < 2:
        return chunks

    out = [chunks[0]]
    for previous, chunk in zip(chunks, chunks[1:], strict=False):
        tail = previous[-OVERLAP:].strip()
        out.append(f"{OVERLAP_MARK}{tail}\n\n{chunk}" if tail else chunk)
    return out
