"""OCR: send a PDF to Google Document AI and hand back what it found.

The pipeline still runs fully offline -- nothing calls this yet. It is the seam
for PDFs when you want one: `extract_pdf` returns raw text and table cells in
plain dataclasses, leaving it to the caller to decide what becomes a Document.

Which processor you point at decides what comes back:

  * Document OCR (`OCR_PROCESSOR`) returns text only -- `tables` stays empty.
  * Form Parser (`FORM_PARSER_PROCESSOR`) returns text *and* table structure.

Both are configured the same way -- DOCAI_PROJECT_ID, DOCAI_LOCATION and
DOCAI_PROCESSOR_ID (see backend/.env.example), plus GOOGLE_APPLICATION_CREDENTIALS
pointing at a service account key file. That last one is read by the Google auth
library from the real environment, not from .env.
"""

import io
import re
from dataclasses import dataclass
from pathlib import Path

from google.api_core import exceptions as gax_exceptions
from google.auth import exceptions as auth_exceptions
from google.cloud import documentai
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.config import settings

# Online (synchronous) processing caps the whole request at 20 MB. Larger files
# need batch processing, which is a different API that writes its results to
# Cloud Storage -- refuse here rather than send a request that cannot succeed.
MAX_REQUEST_BYTES = 20 * 1024 * 1024

# Most processors also cap online requests at 15 pages. Google's docs describe
# an "imageless mode" that raises this to 30 -- tried here and reverted, since
# the processor this project uses (a Form Parser) enforces 15 regardless and
# returns a vaguer 500 instead of the usual 400 when it is set.
#
# Document AI's own enforcement of this limit is not reliable: the same
# over-limit file has been seen to return a clean 400 on one call and, on an
# otherwise identical retry, silently succeed while returning only the first
# ONLINE_PAGE_LIMIT pages -- no error, no indication anything was cut. Pages
# are counted locally with pypdf instead of trusting the API to say so; see
# `_count_pages` and the InvalidArgument branch in `_process`, which stays as
# a backstop for files pypdf itself cannot parse.
ONLINE_PAGE_LIMIT = 15

# Three or more line breaks, left behind when a table is cut out from between
# two paragraphs.
_BLANK_LINES_RE = re.compile(r"\n{3,}")


class OcrError(RuntimeError):
    """Document AI could not be reached, or refused the request.

    The message is written to be printed as-is, so callers do not have to know
    Google's exception types to say something useful.
    """


class FileTooLarge(OcrError):
    """The file is over the online-processing size limit.

    Separate from the rest because it is the caller's fault rather than the
    service's, and it is decided here without a request being sent. Its message
    names only sizes -- no project or processor -- so it is safe to hand back to
    whoever supplied the file. Subclasses OcrError so callers that only care
    that OCR failed still catch it.
    """


class TooManyPages(OcrError):
    """The PDF has more pages than the online-processing limit allows.

    Decided locally, same reasoning as `FileTooLarge` -- and more load-bearing
    here, since Document AI's own rejection of an over-limit file is not
    reliable (see `ONLINE_PAGE_LIMIT`). Its message names only a page count,
    so it is safe to hand back to whoever supplied the file.
    """


@dataclass(frozen=True)
class Table:
    """One table on one page, as cell text. No merged spans, no styling."""

    page_number: int
    header_rows: list[list[str]]
    body_rows: list[list[str]]

    @property
    def rows(self) -> list[list[str]]:
        """Header and body together, in reading order."""
        return self.header_rows + self.body_rows


@dataclass(frozen=True)
class OcrResult:
    """Everything the processor returned that we care about."""

    text: str
    page_count: int
    tables: list[Table]
    prose: str = ""
    """`text` with the table regions cut out.

    Document AI returns one flat string holding everything on the page, tables
    included -- and a table flattened into that string is one cell per line with
    no punctuation, which is both a duplicate of `tables` and unreadable to
    anything downstream. Callers that render `tables` themselves want this
    instead of `text`, so the same cells are not stored twice.
    """


def extract_pdf(
    path: str | Path,
    *,
    project_id: str | None = None,
    location: str | None = None,
    processor_id: str | None = None,
) -> OcrResult:
    """Run one PDF through Document AI and return its text and tables.

    Credentials and processor come from settings unless overridden. Raises
    `OcrError` for anything that goes wrong, including an unreadable file.
    """
    pdf_path = Path(path)
    try:
        content = pdf_path.read_bytes()
    except OSError as e:
        raise OcrError(f"Could not read {pdf_path}: {e}") from e

    if not content:
        raise OcrError(f"{pdf_path} is empty.")

    return extract_bytes(
        content,
        project_id=project_id,
        location=location,
        processor_id=processor_id,
    )


def extract_bytes(
    content: bytes,
    *,
    mime_type: str = "application/pdf",
    project_id: str | None = None,
    location: str | None = None,
    processor_id: str | None = None,
) -> OcrResult:
    """As `extract_pdf`, for bytes already in hand -- an upload, say."""
    # Size first: a file too big to send is too big whether or not a processor
    # has been configured, and reporting missing configuration instead sends the
    # caller off fixing the wrong thing.
    if len(content) > MAX_REQUEST_BYTES:
        raise FileTooLarge(
            f"File is {len(content) / 1024 / 1024:.1f} MB, over the "
            f"{MAX_REQUEST_BYTES // 1024 // 1024} MB limit for online processing. "
            "Files this large need batch processing."
        )

    # Same reasoning, and the more important of the two checks -- see
    # ONLINE_PAGE_LIMIT. A page count of None means pypdf could not parse the
    # file; that is left for Document AI to report, rather than guessed at here.
    page_count = _count_pages(content)
    if page_count is not None and page_count > ONLINE_PAGE_LIMIT:
        raise TooManyPages(
            f"PDF has {page_count} pages, over the {ONLINE_PAGE_LIMIT}-page limit "
            "for online processing. Split it, or use batch processing."
        )

    project_id = project_id or settings.docai_project_id
    location = location or settings.docai_location
    processor_id = processor_id or settings.docai_processor_id

    if not project_id or not processor_id:
        raise OcrError("Set DOCAI_PROJECT_ID and DOCAI_PROCESSOR_ID (see backend/.env.example).")

    document = _process(content, mime_type, project_id, location, processor_id)
    return OcrResult(
        text=document.text,
        page_count=len(document.pages),
        tables=_read_tables(document),
        prose=_text_outside_tables(document),
    )


def _count_pages(content: bytes) -> int | None:
    """Best-effort page count, without asking Document AI.

    Returns None rather than raising if the bytes cannot be parsed as a PDF at
    all -- an encrypted or malformed file, say. Document AI's own error for a
    file it cannot read is clearer than anything worth constructing here, so an
    unparseable file just skips this check and goes on to the API.
    """
    try:
        return len(PdfReader(io.BytesIO(content)).pages)
    except (PdfReadError, ValueError):
        return None


def _process(
    content: bytes,
    mime_type: str,
    project_id: str,
    location: str,
    processor_id: str,
) -> documentai.Document:
    """The API call, with Google's failure modes translated into OcrError."""
    try:
        client = documentai.DocumentProcessorServiceClient(
            client_options={"api_endpoint": f"{location}-documentai.googleapis.com"}
        )
        request = documentai.ProcessRequest(
            name=client.processor_path(project_id, location, processor_id),
            raw_document=documentai.RawDocument(content=content, mime_type=mime_type),
        )
        return client.process_document(request=request).document
    except auth_exceptions.DefaultCredentialsError as e:
        raise OcrError(
            "No credentials found. Set GOOGLE_APPLICATION_CREDENTIALS to a "
            "service account key file."
        ) from e
    except auth_exceptions.RefreshError as e:
        raise OcrError(
            "Credentials were rejected. The key file may be invalid or the key revoked."
        ) from e
    except gax_exceptions.InvalidArgument as e:
        # The usual causes: a PDF over the online page limit, or bytes that are
        # not the mime type we claimed they were.
        raise OcrError(
            f"Document AI rejected the request (400): {e.message} "
            f"Online processing accepts up to {ONLINE_PAGE_LIMIT} pages of {mime_type}."
        ) from e
    except gax_exceptions.PermissionDenied as e:
        raise OcrError(f"Authenticated, but access was denied (403): {e.message}") from e
    except gax_exceptions.NotFound as e:
        raise OcrError(
            f"Processor not found (404). Check DOCAI_PROJECT_ID={project_id!r}, "
            f"DOCAI_LOCATION={location!r}, DOCAI_PROCESSOR_ID={processor_id!r}."
        ) from e
    except gax_exceptions.ResourceExhausted as e:
        raise OcrError(f"Rate limited or over quota (429): {e.message}") from e
    except gax_exceptions.GoogleAPICallError as e:
        raise OcrError(f"API error: {e.message}") from e


def _read_tables(document: documentai.Document) -> list[Table]:
    """Collect every table on every page, in page order."""
    tables: list[Table] = []
    for position, page in enumerate(document.pages, start=1):
        for table in page.tables:
            tables.append(
                Table(
                    # page_number is 1-based and set by the service; fall back
                    # to position for processors that leave it at zero.
                    page_number=page.page_number or position,
                    header_rows=[_read_row(row, document.text) for row in table.header_rows],
                    body_rows=[_read_row(row, document.text) for row in table.body_rows],
                )
            )
    return tables


def _text_outside_tables(document: documentai.Document) -> str:
    """Everything on the page that is not part of a table.

    Each table's own layout anchor gives the span it occupies in `document.text`,
    so the regions are cut by offset rather than by matching cell strings back
    against the text -- a cell reading "Revenue" would otherwise take a paragraph
    line of the same text with it.
    """
    spans = [
        (int(segment.start_index), int(segment.end_index))
        for page in document.pages
        for table in page.tables
        for segment in table.layout.text_anchor.text_segments
    ]
    return _remove_spans(document.text, spans)


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Cut half-open [start, end) ranges out of text, tidying what is left.

    Spans are merged first: they can overlap or nest, and cutting them one at a
    time would shift every offset that follows.
    """
    if not spans:
        return text.strip()

    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    kept: list[str] = []
    cursor = 0
    for start, end in merged:
        kept.append(text[cursor:start])
        cursor = end
    kept.append(text[cursor:])

    # Removing a block from the middle leaves the blank lines that surrounded it
    # stacked together.
    return _BLANK_LINES_RE.sub("\n\n", "".join(kept)).strip()


def _read_row(row: documentai.Document.Page.Table.TableRow, full_text: str) -> list[str]:
    return [_anchor_text(cell.layout.text_anchor, full_text) for cell in row.cells]


def _anchor_text(anchor: documentai.Document.TextAnchor, full_text: str) -> str:
    """Resolve a text anchor into the substring it points at.

    Document AI never repeats text: every layout element carries offsets into
    the single `document.text` string instead. A cell can span more than one
    segment, so they are concatenated.
    """
    return "".join(
        full_text[int(segment.start_index) : int(segment.end_index)]
        for segment in anchor.text_segments
    ).strip()
