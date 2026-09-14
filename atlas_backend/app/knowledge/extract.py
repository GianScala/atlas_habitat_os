"""Turning an uploaded file into plain text.

PDF, Word, CSV, and plain text, which is what a habitat's procedures, checklists
and contact sheets actually arrive as. Each format has one job here: get the
words out, keep enough structure that a chunk still makes sense on its own, and
refuse clearly when the file is not what it claims to be.

The parsers for PDF and Word are optional installs. A missing one is reported as
a plain sentence naming the package, not a stack trace: an operator uploading a
PDF on a fresh machine should be told what to install, not what crashed.
"""

import csv
import io
from pathlib import Path

from app.core.errors import AtlasError

# Extension -> the human name used in messages.
SUPPORTED = {
    ".pdf": "PDF",
    ".docx": "Word document",
    ".csv": "CSV",
    ".txt": "text file",
    ".md": "Markdown",
}


def supported_note() -> str:
    return "PDF, Word (.docx), CSV, or plain text (.txt, .md)"


def extract(filename: str, data: bytes) -> str:
    """The text of one uploaded file.

    Raises AtlasError with a readable reason for an unsupported type, a
    missing parser, or a file that cannot be read.
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise AtlasError(
            f"{filename} is a {suffix or 'file with no extension'}, which cannot "
            f"be read. Upload {supported_note()}."
        )

    if suffix == ".pdf":
        return _from_pdf(filename, data)
    if suffix == ".docx":
        return _from_docx(filename, data)
    if suffix == ".csv":
        return _from_csv(filename, data)
    return _from_text(filename, data)


def _from_pdf(filename: str, data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - environment, not logic
        raise AtlasError(
            "Reading PDFs needs the pypdf package: pip install pypdf"
        ) from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise AtlasError(f"{filename} could not be opened as a PDF: {exc}") from exc

    # Page numbers are kept because a procedure is cited by page, and a reader
    # sent to "page 4" can check the answer against the paper copy.
    pages: list[str] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text.strip():
            pages.append(f"[page {number}]\n{text.strip()}")

    if not pages:
        raise AtlasError(
            f"{filename} has no extractable text. A scanned PDF needs OCR before "
            "it can be searched."
        )
    return "\n\n".join(pages)


def _from_docx(filename: str, data: bytes) -> str:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover - environment, not logic
        raise AtlasError(
            "Reading Word documents needs the python-docx package: "
            "pip install python-docx"
        ) from exc

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise AtlasError(
            f"{filename} could not be opened as a Word document: {exc}"
        ) from exc

    parts = [p.text.strip() for p in document.paragraphs if p.text.strip()]

    # Tables carry the contact lists and limit values that make a procedure
    # document worth searching, so they are flattened rather than dropped.
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))

    if not parts:
        raise AtlasError(f"{filename} contains no text.")
    return "\n".join(parts)


def _from_csv(filename: str, data: bytes) -> str:
    """A CSV as one line per row, each cell labelled by its column.

    Labelled rather than comma-joined so a row still means something when it is
    retrieved on its own: "Name: Medical lead, Extension: 214" survives being
    lifted out of the table; "Medical lead, 214" does not.
    """
    text = _decode(filename, data)
    reader = csv.reader(io.StringIO(text))
    try:
        rows = list(reader)
    except csv.Error as exc:
        raise AtlasError(f"{filename} could not be read as CSV: {exc}") from exc

    if not rows:
        raise AtlasError(f"{filename} is empty.")

    header = [cell.strip() for cell in rows[0]]
    lines = [" | ".join(header)]
    for row in rows[1:]:
        pairs = [
            f"{header[index]}: {value.strip()}"
            for index, value in enumerate(row)
            if index < len(header) and value.strip()
        ]
        if pairs:
            lines.append(", ".join(pairs))
    return "\n".join(lines)


def _from_text(filename: str, data: bytes) -> str:
    text = _decode(filename, data).strip()
    if not text:
        raise AtlasError(f"{filename} is empty.")
    return text


def _decode(filename: str, data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise AtlasError(f"{filename} is not text this can read.")
