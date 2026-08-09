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
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from google.api_core import exceptions as gax_exceptions
from google.auth import exceptions as auth_exceptions
from google.cloud import documentai, storage
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.config import settings

# pypdf reports recoverable parse issues ("EOF marker not found", "Ignoring
# wrong pointing object...") as logging.WARNING through the stdlib logging
# module. With no handler configured that reaches Python's "handler of last
# resort" and prints straight to stderr. _count_pages already treats a file
# pypdf can't cleanly parse as unreadable and defers to Document AI's own
# error, so the warning itself is noise rather than something to act on.
logging.getLogger("pypdf").setLevel(logging.ERROR)

# Online (synchronous) processing caps the whole request at 20 MB. A file over
# that routes to batch processing instead of being rejected, same as a page
# count over ONLINE_PAGE_LIMIT does -- see `extract_bytes`. Batch raises the
# ceiling to 1 GB, Document AI's own cap for a single document; only a file
# over BATCH_REQUEST_BYTES has no processing path left at all.
ONLINE_REQUEST_BYTES = 20 * 1024 * 1024
BATCH_REQUEST_BYTES = 1024 * 1024 * 1024

# Most processors also cap online (synchronous) requests at 15 pages. Google's
# docs describe an "imageless mode" that raises this to 30 -- tried here and
# reverted, since the processor this project uses (a Form Parser) enforces 15
# regardless and returns a vaguer 500 instead of the usual 400 when it is set.
# A PDF over this limit goes through batch processing instead (see
# `_process_batch`), which has no such issue since it never takes this path.
#
# Document AI's own enforcement of this limit is not reliable: the same
# over-limit file has been seen to return a clean 400 on one call and, on an
# otherwise identical retry, silently succeed while returning only the first
# ONLINE_PAGE_LIMIT pages -- no error, no indication anything was cut. Pages
# are counted locally with pypdf instead of trusting the API to say so; see
# `_count_pages` and the InvalidArgument branch in `_process`, which stays as
# a backstop for files pypdf itself cannot parse.
ONLINE_PAGE_LIMIT = 15

# Document AI's own cap for a single document in a batch (asynchronous)
# request. A PDF over this has no processing path available at all.
BATCH_PAGE_LIMIT = 500

# How long to wait for a batch job to finish before giving up. `extract_bytes`
# runs on a worker thread (see app/ingestion/service.py), so blocking here
# blocks only that thread, not the event loop -- but it still has to give up
# at some point rather than hang forever if Document AI never finishes.
BATCH_TIMEOUT_SECONDS = 600

# Three or more line breaks, left behind when a table is cut out from between
# two paragraphs.
_BLANK_LINES_RE = re.compile(r"\n{3,}")


class OcrError(RuntimeError):
    """Document AI could not be reached, or refused the request.

    The message is written to be printed as-is, so callers do not have to know
    Google's exception types to say something useful.
    """


class FileTooLarge(OcrError):
    """The file is over the size limit Document AI's batch API allows.

    Decided locally, without a request being sent, same reasoning as
    `TooManyPages`. A file over `ONLINE_REQUEST_BYTES` but within
    `BATCH_REQUEST_BYTES` is not an error at all; it just routes to
    `_process_batch` instead of `_process`. Its message names only sizes -- no
    project or processor -- so it is safe to hand back to whoever supplied the
    file. Subclasses OcrError so callers that only care that OCR failed still
    catch it.
    """


class TooManyPages(OcrError):
    """The PDF has more pages than Document AI's batch API allows.

    Decided locally, same reasoning as `FileTooLarge` -- and more load-bearing
    here, since Document AI's own rejection of an over-limit online request is
    not reliable (see `ONLINE_PAGE_LIMIT`). A page count over `ONLINE_PAGE_LIMIT`
    but within `BATCH_PAGE_LIMIT` is not an error at all; it just routes to
    `_process_batch` instead. Its message names only a page count, so it is
    safe to hand back to whoever supplied the file.
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
    # Size first: a file too big for even batch processing is too big whether
    # or not a processor has been configured, and reporting missing
    # configuration instead sends the caller off fixing the wrong thing.
    if len(content) > BATCH_REQUEST_BYTES:
        raise FileTooLarge(
            f"File is {len(content) / 1024 / 1024:.1f} MB, over the "
            f"{BATCH_REQUEST_BYTES // 1024 // 1024} MB limit Document AI's batch "
            "processing allows."
        )

    # Same reasoning, and the more important of the two checks -- see
    # ONLINE_PAGE_LIMIT. A page count of None means pypdf could not parse the
    # file; that is left for Document AI to report, rather than guessed at here.
    page_count = _count_pages(content)
    if page_count is not None and page_count > BATCH_PAGE_LIMIT:
        raise TooManyPages(
            f"PDF has {page_count} pages, over the {BATCH_PAGE_LIMIT}-page limit "
            "Document AI's batch processing allows. Split it into smaller files."
        )

    project_id = project_id or settings.docai_project_id
    location = location or settings.docai_location
    processor_id = processor_id or settings.docai_processor_id

    if not project_id or not processor_id:
        raise OcrError("Set DOCAI_PROJECT_ID and DOCAI_PROCESSOR_ID (see backend/.env.example).")

    # Either dimension alone can force batch: a file can be small enough in
    # bytes but too long in pages, or short enough in pages but too heavy in
    # bytes (a lot of embedded images, say).
    needs_batch = len(content) > ONLINE_REQUEST_BYTES or (
        page_count is not None and page_count > ONLINE_PAGE_LIMIT
    )
    if needs_batch:
        documents = _process_batch(content, mime_type, project_id, location, processor_id)
    else:
        documents = [_process(content, mime_type, project_id, location, processor_id)]
    return _build_result(documents)


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


def _process_batch(
    content: bytes,
    mime_type: str,
    project_id: str,
    location: str,
    processor_id: str,
) -> list[documentai.Document]:
    """As `_process`, for PDFs over ONLINE_PAGE_LIMIT pages or ONLINE_REQUEST_BYTES.

    Document AI's batch API reads its input from Cloud Storage and writes its
    output there too, rather than taking the file directly and returning a
    response -- so this uploads `content`, waits on the resulting operation,
    and reads back whatever JSON it wrote. A large document can come back
    split across more than one output file ("shard"); `_build_result` puts the
    pieces back together, so every caller gets a single list back either way.

    The bucket is scratch space, not storage: everything written under this
    job's prefix is deleted again before returning, success or failure.
    """
    if not settings.docai_gcs_bucket:
        raise OcrError(
            "Set DOCAI_GCS_BUCKET (see backend/.env.example) to process PDFs over "
            f"{ONLINE_PAGE_LIMIT} pages or {ONLINE_REQUEST_BYTES // 1024 // 1024} MB -- "
            "Document AI's batch API reads and writes Cloud Storage rather than "
            "taking the file directly."
        )

    job_prefix = f"docai-batch/{uuid.uuid4().hex}/"
    input_uri = f"gs://{settings.docai_gcs_bucket}/{job_prefix}input.pdf"
    output_uri = f"gs://{settings.docai_gcs_bucket}/{job_prefix}output/"
    storage_client = storage.Client(project=project_id)

    try:
        storage_client.bucket(settings.docai_gcs_bucket).blob(
            f"{job_prefix}input.pdf"
        ).upload_from_string(content, content_type=mime_type)

        client = documentai.DocumentProcessorServiceClient(
            client_options={"api_endpoint": f"{location}-documentai.googleapis.com"}
        )
        request = documentai.BatchProcessRequest(
            name=client.processor_path(project_id, location, processor_id),
            input_documents=documentai.BatchDocumentsInputConfig(
                gcs_documents=documentai.GcsDocuments(
                    documents=[documentai.GcsDocument(gcs_uri=input_uri, mime_type=mime_type)]
                )
            ),
            document_output_config=documentai.DocumentOutputConfig(
                gcs_output_config=documentai.DocumentOutputConfig.GcsOutputConfig(gcs_uri=output_uri)
            ),
        )
        operation = client.batch_process_documents(request=request)
        try:
            # Polls on the client library's own backoff schedule and blocks
            # this call's thread until the job finishes -- fine here since
            # extract_bytes already runs off the event loop (see
            # app/ingestion/service.py).
            operation.result(timeout=BATCH_TIMEOUT_SECONDS)
        except TimeoutError as e:
            raise OcrError(
                f"Document AI's batch job did not finish within {BATCH_TIMEOUT_SECONDS}s."
            ) from e

        metadata = documentai.BatchProcessMetadata(operation.metadata)
        if metadata.state != documentai.BatchProcessMetadata.State.SUCCEEDED:
            raise OcrError(f"Document AI's batch job failed: {metadata.state_message}")

        return [
            documentai.Document.from_json(blob.download_as_bytes(), ignore_unknown_fields=True)
            for status in metadata.individual_process_statuses
            for blob in storage_client.list_blobs(
                settings.docai_gcs_bucket,
                prefix=status.output_gcs_destination.removeprefix(
                    f"gs://{settings.docai_gcs_bucket}/"
                ),
            )
            if blob.name.endswith(".json")
        ]
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
        raise OcrError(f"Document AI rejected the batch request (400): {e.message}") from e
    except gax_exceptions.PermissionDenied as e:
        raise OcrError(f"Authenticated, but access was denied (403): {e.message}") from e
    except gax_exceptions.Forbidden as e:
        raise OcrError(
            f"Access to gs://{settings.docai_gcs_bucket} was denied (403): {e.message}"
        ) from e
    except gax_exceptions.NotFound as e:
        raise OcrError(
            f"Not found (404): {e.message} Check DOCAI_PROJECT_ID={project_id!r}, "
            f"DOCAI_LOCATION={location!r}, DOCAI_PROCESSOR_ID={processor_id!r}, and "
            f"DOCAI_GCS_BUCKET={settings.docai_gcs_bucket!r}."
        ) from e
    except gax_exceptions.ResourceExhausted as e:
        raise OcrError(f"Rate limited or over quota (429): {e.message}") from e
    except gax_exceptions.GoogleAPICallError as e:
        raise OcrError(f"API error: {e.message}") from e
    finally:
        for blob in storage_client.list_blobs(settings.docai_gcs_bucket, prefix=job_prefix):
            blob.delete()


def _build_result(documents: list[documentai.Document]) -> OcrResult:
    """Combine one or more Document AI results into the shape callers see.

    A single element for the online path. More than one when a batch job
    split a large PDF across output shards -- each shard is a self-contained
    Document whose text/table/page fields only need concatenating, not
    re-anchoring, since Document AI's shard boundaries fall on page breaks.
    """
    return OcrResult(
        text="\n\n".join(document.text for document in documents),
        page_count=sum(len(document.pages) for document in documents),
        tables=[table for document in documents for table in _read_tables(document)],
        prose="\n\n".join(
            prose for document in documents if (prose := _build_prose(document))
        ),
    )


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


# Selection marks Document AI embeds inline in `document.text` (e.g. "☑
# Natural gas") are usually reliable, but empirically not for one specific
# layout: a single text label preceded by two or more unlabeled checkboxes
# for different items/units (e.g. "☐ ☐ ☐ Unsafe Flue angle
# down" -- a per-unit A/B/C selection). For that shape, `document.text`
# sometimes drops every mark on the row and sometimes keeps a mark in the
# wrong state; the label itself always survives, since normal OCR is what
# recognizes it as running text -- the marks do not reliably make it into
# that same text stream at all.
#
# Document AI's vision-level detector (`page.visual_elements`, type
# "filled_checkbox" / "unfilled_checkbox") finds these same marks even when
# the text stream drops them, but reports each as a bare glyph with a
# bounding box and no attached label. `page.form_fields`, which does try to
# pair a mark with its nearest label, was checked against this exact layout
# and is *wrong* more often than the (already unreliable) inline text: it
# defaults to "unfilled_checkbox" almost regardless of the true state, which
# would trade false positives for silently dropped real findings.
#
# So the fix is geometric: match each checkbox visual element to the text
# line it sits on (same normalized y-band) rather than trusting either of
# Document AI's own attempts at that pairing. A line matched to two or more
# checkboxes is corrected in place -- overwriting whatever marks, if any,
# Document AI's own text recognition put there, since this project has never
# found the inline text trustworthy for that specific shape. A line matched
# to zero or one checkbox is left untouched: a single checkbox immediately
# before its own label is the common case, and already comes through the
# text stream correctly.
#
# Corrections are anchored to each line's own text_anchor span and applied by
# offset, in the same pass as cutting table regions -- never by searching for
# a line's text in a string. Report templates reuse identical short labels
# ("Appears Serviceable", "Comments", ...) across dozens of lines, only some
# of which need correction; a content-based search-and-replace was tried
# first and confirmed (on real report data) to sometimes edit the wrong
# occurrence of a repeated label instead of the one it was computed for.
_CHECKBOX_VISUAL_TYPES = {"filled_checkbox", "unfilled_checkbox"}
_CHECKBOX_GLYPHS = {"filled_checkbox": "☑", "unfilled_checkbox": "☐"}

# A run of one or more checkbox glyphs (with optional spacing) at the start
# of a line -- stripped before re-prefixing with geometry-resolved marks, so
# a corrected line is never double-marked.
_LEADING_CHECKBOX_RUN_RE = re.compile(r"^(?:[☐☑☒]\s*)+")

# A line whose entire text is checkbox glyphs and nothing else -- Document AI
# sometimes recognizes an isolated checkbox as its own line rather than
# folding it into the adjacent label's line. Such a line carries no label of
# its own, but it can still sit close enough to a real label line to win a
# checkbox's nearest-line match instead of that label -- excluded from the
# candidate lines below so it can never steal a match meant for its neighbor.
_CHECKBOX_ONLY_LINE_RE = re.compile(r"^[☐☑☒\s]+$")


def _bbox_y_range(layout: documentai.Document.Page.Layout) -> tuple[float, float] | None:
    ys = [v.y for v in layout.bounding_poly.normalized_vertices]
    return (min(ys), max(ys)) if ys else None


def _bbox_x_center(layout: documentai.Document.Page.Layout) -> float | None:
    xs = [v.x for v in layout.bounding_poly.normalized_vertices]
    return (min(xs) + max(xs)) / 2 if xs else None


# A checkbox with no line within this many normalized-page units of it (in
# y) is treated as unmatched rather than forced onto the nearest one anyway
# -- roughly one and a half line-heights on a typical page, loose enough for
# ordinary layout jitter, tight enough that a checkbox on a genuinely
# different part of the page cannot get pulled onto a distant line.
_MAX_CHECKBOX_LINE_DISTANCE = 0.02


def _checkbox_line_corrections(document: documentai.Document) -> list[tuple[int, int, str]]:
    """(start, end, replacement) edits, by offset into `document.text`, for
    lines whose checkbox marks need correcting -- see the module comment
    above `_CHECKBOX_VISUAL_TYPES`.
    """
    edits: list[tuple[int, int, str]] = []

    for page in document.pages:
        checkboxes = [ve for ve in page.visual_elements if ve.type_ in _CHECKBOX_VISUAL_TYPES]
        if not checkboxes:
            continue

        lines: list[tuple[int, int, float]] = []
        for line in page.lines:
            segments = list(line.layout.text_anchor.text_segments)
            if len(segments) != 1:
                continue  # A wrapped/multi-segment line has no single span to replace; left as Document AI wrote it.
            start, end = int(segments[0].start_index), int(segments[0].end_index)
            if start >= end:
                continue
            if _CHECKBOX_ONLY_LINE_RE.match(document.text[start:end]):
                continue  # See _CHECKBOX_ONLY_LINE_RE: not a label, must not compete with its neighbor for matches.
            line_y = _bbox_y_range(line.layout)
            if line_y is None:
                continue
            lines.append((start, end, sum(line_y) / 2))
        if not lines:
            continue

        # Each checkbox is assigned to the single nearest line by y-center,
        # not to every line within a tolerance band -- rows in some report
        # templates are packed close enough that a generous per-line band
        # matches a checkbox that actually belongs to the row above or
        # below, corrupting both rows' resolved marks. Nearest-line
        # assignment partitions the page at the midpoint between adjacent
        # rows instead, which held up against real report data where the
        # tolerance-band approach did not.
        matches_by_line: dict[int, list[tuple[float, str]]] = {}
        for checkbox in checkboxes:
            checkbox_y = _bbox_y_range(checkbox.layout)
            x_center = _bbox_x_center(checkbox.layout)
            if checkbox_y is None or x_center is None:
                continue
            y_center = sum(checkbox_y) / 2
            nearest_index, distance = min(
                ((i, abs(y_center - line_y)) for i, (_, _, line_y) in enumerate(lines)),
                key=lambda pair: pair[1],
            )
            if distance > _MAX_CHECKBOX_LINE_DISTANCE:
                continue
            matches_by_line.setdefault(nearest_index, []).append((x_center, checkbox.type_))

        for index, matches in matches_by_line.items():
            if len(matches) < 2:
                continue  # A single checkbox on its own line already comes through correctly.
            start, end, _ = lines[index]
            matches.sort()
            marks = "".join(f"{_CHECKBOX_GLYPHS[kind]} " for _, kind in matches)
            original = document.text[start:end]
            corrected = marks + _LEADING_CHECKBOX_RUN_RE.sub("", original)
            if corrected != original:
                edits.append((start, end, corrected))

    return edits


def _merge_spans(spans: list[tuple[int, int]]) -> list[list[int]]:
    """Sort and merge overlapping/nested half-open [start, end) spans.

    Spans returned by Document AI (a table's layout, say) can overlap or
    nest; cutting or replacing them one at a time in the original order would
    shift every offset that follows.
    """
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Cut half-open [start, end) ranges out of text, tidying what is left."""
    if not spans:
        return text.strip()

    kept: list[str] = []
    cursor = 0
    for start, end in _merge_spans(spans):
        kept.append(text[cursor:start])
        cursor = end
    kept.append(text[cursor:])

    # Removing a block from the middle leaves the blank lines that surrounded it
    # stacked together.
    return _BLANK_LINES_RE.sub("\n\n", "".join(kept)).strip()


def _build_prose(document: documentai.Document) -> str:
    """Everything on the page that is not part of a table, with ambiguous
    checkbox lines corrected -- see `_checkbox_line_corrections` and the
    module comment above `_CHECKBOX_VISUAL_TYPES`.

    Each table's own layout anchor gives the span it occupies in
    `document.text`, so table regions are cut by offset rather than by
    matching cell strings back against the text -- a cell reading "Revenue"
    would otherwise take a paragraph line of the same text with it. Checkbox
    corrections are applied in the same offset-based pass, so the two kinds
    of edit can never disagree about what shifted where.
    """
    table_spans = [
        (int(segment.start_index), int(segment.end_index))
        for page in document.pages
        for table in page.tables
        for segment in table.layout.text_anchor.text_segments
    ]
    removals = _merge_spans(table_spans)

    def _overlaps_a_removal(start: int, end: int) -> bool:
        return any(r_start < end and start < r_end for r_start, r_end in removals)

    edits: list[tuple[int, int, str]] = [(start, end, "") for start, end in removals]
    edits += [
        (start, end, replacement)
        for start, end, replacement in _checkbox_line_corrections(document)
        # A correction inside a span already being cut for a table is
        # redundant -- that text is discarded either way -- and keeping it
        # would risk two edits overlapping in the pass below.
        if not _overlaps_a_removal(start, end)
    ]
    edits.sort()

    text = document.text
    kept: list[str] = []
    cursor = 0
    for start, end, replacement in edits:
        if start < cursor:
            continue  # Two edits should never overlap once table spans are pre-merged and checkbox edits are filtered against them; skip defensively rather than risk corrupting output if one slips through.
        kept.append(text[cursor:start])
        kept.append(replacement)
        cursor = end
    kept.append(text[cursor:])

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
