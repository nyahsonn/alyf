# ALYF

ALYF turns a home inspection report into an **AI Home Health Report**: a structured,
prioritized, continuously updatable picture of a home's systems — roof, HVAC, plumbing,
electrical, water heater, foundation — with an age, a condition, findings, and a
confidence score per field. Distribution is B2B2C through home inspectors: an
inspector's commodity PDF becomes a premium, white-labeled deliverable handed to buyers
at the point of sale, and every report run adds to ALYF's own structured, verified
database of home data over time.

Under that product sits a general **document-understanding pipeline** — raw source
material goes in, structured facts and Markdown reports come out — built as a
**modular monolith**: one deployable backend, four modules with clear seams between
them. Documents flow through the stages in order:

```
ingestion  ->  extraction  ->  reasoning  ->  reports
  chunk         facts +         vector        assemble
  text          embeddings      search        Markdown
```

Each module owns its own tables, schemas, and service functions, and talks to its
neighbours only through service calls — never by querying another module's tables.
`reports` is the only stage that reads across the others.

**Most of it runs entirely offline.** No API keys, no model downloads. The embedder is a
deterministic hashing embedder and the generic extractor is rule-based, so you can stand
the whole thing up — including real pgvector similarity search inside PostgreSQL — and
watch data move end to end without any credentials. The one real extraction path that
matters for the actual product, `POST /documents/{id}/home-report`, calls Claude and
needs `ANTHROPIC_API_KEY`; see
[Going from offline to real models](#going-from-offline-to-real-models).

Uploading a [PDF](#pdfs) also calls out — to Google Document AI for OCR. Text uploads,
and every stage after ingestion apart from the home report, still need no credentials.

## Stack

| Layer    | Choice                                                        |
| -------- | ------------------------------------------------------------- |
| Backend  | FastAPI, SQLAlchemy 2 (async), Pydantic v2, Python ≥ 3.11      |
| Database | PostgreSQL 17 + [pgvector](https://github.com/pgvector/pgvector) |
| Frontend | Next.js 16, React 19, Tailwind CSS v4, TypeScript             |
| Local    | Docker Compose (database + optional Adminer UI)               |

## Quickstart

Three pieces start in order: database, backend, frontend. Each needs its own env
file, copied from the `.example` beside it — the examples hold working local
defaults, so no editing is required to get started.

### 1. Database

```bash
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
docker compose up -d
```

This brings up PostgreSQL with pgvector on port `5432`, plus Adminer at
http://localhost:8080 for browsing tables. Data lives in a named volume, so it
survives `docker compose down`.

Already running PostgreSQL locally? Set `POSTGRES_PORT` in `.env` to something free
(e.g. `5433`) and update `DATABASE_URL` in `backend/.env` to match.

### 2. Backend

```bash
cd backend
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env

python -m venv .venv
source .venv/bin/activate     # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000
```

Tables are created on startup if missing, and the pgvector extension is enabled — no
migration step for a fresh database. Interactive API docs land at
http://localhost:8000/docs.

If startup fails with a connection error, the database isn't reachable: check
`docker compose ps` and confirm `DATABASE_URL` in `backend/.env` matches the
credentials and port in the root `.env`.

### 3. Frontend

```bash
cd frontend
cp .env.local.example .env.local   # PowerShell: Copy-Item .env.local.example .env.local

npm install
npm run dev
```

The UI is at http://localhost:3000 — ingest a document, extract facts, ask questions,
and generate a report, with a banner showing backend and database health.

### Try it with the sample

`data/samples/sample-inspection-report.md` is a short home inspection report covering
the six systems ALYF tracks, written in the shape the rule-based extractor also
recognises (`Label: value` lines plus prose with figures). Paste it into the UI, or
upload it directly:

```bash
curl -F "file=@data/samples/sample-inspection-report.md" http://localhost:8000/api/v1/documents/upload
```

Then, using the returned document id:

- `POST /documents/{id}/extract` runs the offline, rule-based extractor and lets you
  ask questions like *"what did the inspector say about the HVAC?"*
- `POST /documents/{id}/home-report` is the real product path: it sends the document's
  text to Claude and returns the AI Home Health Report, one entry per system with an
  age, a condition, findings, and a confidence score per field. Needs
  `ANTHROPIC_API_KEY` set as a real environment variable — see
  [Configuration](#configuration).

### PDFs

In production this is almost always a home inspector's report. `POST /documents/upload`
recognises a PDF from its own bytes — not the filename or the browser's content type —
and sends it to Google Document AI for OCR. Everything else must be UTF-8 text, and is
rejected with a `415` if it is not. Documents that arrive this way are stored with
`source_type: "pdf"`.

Point `DOCAI_PROCESSOR_ID` at a **Form Parser** processor. A plain Document OCR
processor returns text alone, and tables are the reason to use OCR at all: Document
AI flattens a table into one cell per line, which loses the link between a number and
the row and column it came from. The table regions are cut out of that text and
re-emitted as `Label: value` lines instead, which is the shape the rule-based
extractor reads — so `Revenue Q2: 5.1M` becomes a fact, rather than the whole page
becoming one unusable claim.

Two limits apply to the synchronous Document AI call: 15 pages and 20 MB. Both are
checked locally — pages by counting with `pypdf`, since Document AI's own rejection
of an over-limit file turned out not to be reliable (the same file has been seen to
return a clean error on one call and silently succeed with only the first 15 pages,
no error at all, on the next).

A PDF over either limit — 15 pages or 20 MB — is routed to Document AI's batch API
instead of being rejected, transparently: the caller gets the same `OcrResult` back
either way, just slower, since batch reads its input from Cloud Storage and writes
its output there too rather than returning a response directly. That needs
`DOCAI_GCS_BUCKET` set (see `backend/.env.example`); without it, a PDF over either
online limit fails with a clear error rather than being silently truncated.

Batch has its own, much larger ceiling — 500 pages and 1 GB, Document AI's own caps
for a single document. A PDF over either of *those* has no processing path left at
all and gets a `413` up front, same as any other oversized file.

Check credentials before uploading anything, and look at raw OCR output directly:

```bash
cd backend
python scripts/check_document_ai.py            # credentials + processor reachable?
python scripts/ocr_pdf.py path/to/file.pdf     # raw text and tables, printed
```

## API

All routes are mounted under `/api/v1`.

| Method   | Path                            | Purpose                                        |
| -------- | ------------------------------- | ---------------------------------------------- |
| `GET`    | `/health`                       | Liveness check                                 |
| `GET`    | `/health/db`                    | Database connectivity and pgvector status      |
| `POST`   | `/documents`                    | Ingest a document from a JSON body             |
| `POST`   | `/documents/upload`             | Ingest an uploaded file — PDFs are OCR'd first |
| `GET`    | `/documents`                    | List documents                                 |
| `GET`    | `/documents/{id}`               | Document detail, including its chunks          |
| `DELETE` | `/documents/{id}`               | Delete a document and everything derived from it |
| `POST`   | `/documents/{id}/extract`       | Extract and embed facts for a document         |
| `GET`    | `/facts`                        | List extracted facts                           |
| `POST`   | `/documents/{id}/home-report`   | Generate the AI Home Health Report via Claude  |
| `GET`    | `/documents/{id}/home-report`   | The most recently generated home report, if any |
| `POST`   | `/ask`                          | Vector-search facts and compose an answer      |
| `GET`    | `/insights`                     | List past questions and their answers          |
| `POST`   | `/reports`                      | Generate a Markdown report for a document      |
| `GET`    | `/reports`                      | List reports                                   |
| `GET`    | `/reports/{id}`                 | Report detail, including rendered Markdown     |

## Configuration

Three env files, each with a committed `.example` template. The real files are
gitignored.

**`.env`** (root) — read by `docker-compose.yml`

| Variable            | Default | Notes                        |
| ------------------- | ------- | ---------------------------- |
| `POSTGRES_USER`     | `alyf`  |                              |
| `POSTGRES_PASSWORD` | `alyf`  | Local development only       |
| `POSTGRES_DB`       | `alyf`  |                              |
| `POSTGRES_PORT`     | `5432`  | Host port for the database   |
| `ADMINER_PORT`      | `8080`  | Host port for the Adminer UI |

**`backend/.env`**

| Variable               | Default                                              | Notes                                          |
| ---------------------- | ---------------------------------------------------- | ---------------------------------------------- |
| `ENVIRONMENT`          | `local`                                              |                                                |
| `DEBUG`                | `true`                                               | Sets log level to `DEBUG`                      |
| `DATABASE_URL`         | `postgresql+asyncpg://alyf:alyf@localhost:5432/alyf` | The `+asyncpg` suffix is required              |
| `EMBEDDING_DIMENSIONS` | `384`                                                | Changing this requires recreating `facts`      |
| `CORS_ORIGINS`         | `http://localhost:3000`                              | Comma-separated                                |
| `DOCAI_PROJECT_ID`     | —                                                    | Google Cloud project holding the processor     |
| `DOCAI_LOCATION`       | `us`                                                 | Must match the processor's region              |
| `DOCAI_PROCESSOR_ID`   | —                                                    | Use a **Form Parser** processor — see [PDFs](#pdfs) |
| `DOCAI_GCS_BUCKET`     | —                                                    | Only needed for PDFs over Document AI's online limits — see [PDFs](#pdfs) |
| `ANTHROPIC_API_KEY`    | —                                                    | Needed by `POST /documents/{id}/home-report` and `.../action-plan` |

Document AI also needs `GOOGLE_APPLICATION_CREDENTIALS` pointing at a service account
key file. That one is read from the real environment by the Google auth library, not
from `backend/.env` — setting it there alone is not enough. `ANTHROPIC_API_KEY` works either way: set it in `backend/.env` for local dev, or as a
real environment variable in deployments that don't ship a `.env` file — `backend/.env`
wins if both happen to be set. Only PDF uploads and the home-report/action-plan
endpoints use any of this; everything else needs no credentials.

Chunking is tunable in `backend/app/core/config.py` — `chunk_size_words` (180) and
`chunk_overlap_words` (30).

**`frontend/.env.local`**

| Variable              | Default                 | Notes                                                    |
| --------------------- | ----------------------- | -------------------------------------------------------- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | `NEXT_PUBLIC_` values ship in the browser bundle — no secrets |

## Tests

Thirty-one unit tests cover chunking (4), the rule-based extractor (5), dedupe (6),
answer composition (4), embedding (3), and PDF/table handling (9). They exercise pure
functions only, so no database or running server is needed:

```bash
cd backend
pytest
```

GitHub Actions runs the same command on every push to `main` and every pull
request, against Python 3.11 and 3.13 — see `.github/workflows/tests.yml`.

Ruff is configured in `backend/pyproject.toml` (line length 100, rules `E,F,I,UP,B`)
but is intentionally not a pinned dependency — install it however you prefer:

```bash
pip install ruff   # or: uvx ruff check .
ruff check .
```

## Going from offline to real models

Extraction already has a real, LLM-backed path — the one the product actually runs on.
Two other seams are still deliberately naive so the rest of the system runs with zero
setup, each a single function whose replacement leaves persistence, dedupe, and
retrieval untouched.

- **Home report extraction** — `backend/app/extraction/home_inspection.py`.
  `extract_home_systems` sends a document's text to Claude using structured outputs, so
  the reply always validates against a fixed schema: one entry per home system (roof,
  HVAC, plumbing, electrical, water heater, foundation), each with an estimated age, a
  condition, findings, and its own confidence score per field. `POST
  /documents/{id}/home-report` runs it and persists the result to
  `home_system_records`, replacing any earlier run for that document. This is the path
  the actual product uses; it needs `ANTHROPIC_API_KEY`.
- **Rule-based extraction** — `backend/app/extraction/service.py`. `extract_candidates`
  uses regex to find `Label: value` pairs and figures in prose, with no model call at
  all. This is what `POST /documents/{id}/extract` still runs, kept for the offline
  demo path described above rather than for the home-report product itself.
- **Embeddings** — `backend/app/core/embeddings.py`. `embed_text` hashes tokens and
  word pairs into a unit-length vector. It is deterministic but not semantically
  meaningful: similarity reflects shared wording, not shared meaning. Replace the body
  with a provider call, set `EMBEDDING_DIMENSIONS` to that model's dimension, and
  recreate the `facts` table (the vector column is fixed-width).
- **Answer composition** — `backend/app/reasoning/service.py`. Retrieval is already
  real pgvector search (`cosine_distance` compiles to the `<=>` operator and runs in
  PostgreSQL). Only `compose_answer` is extractive — it quotes retrieved facts rather
  than generating prose. Replace it to make answers generative; retrieval keeps
  working as is.

## Layout

```
backend/
  app/
    api/            route definitions, aggregated in router.py
    core/           config, database engine, embeddings
    ingestion/      chunking            models / schemas / service
    extraction/     facts + embeddings  models / schemas / service
    reasoning/      vector search       models / schemas / service
    reports/        Markdown assembly   models / schemas / service
    main.py         app factory, CORS, startup schema creation
  tests/
frontend/
  src/app/          Next.js App Router pages
  src/lib/api.ts    typed client for the backend
data/samples/       example input documents
db/init/            SQL run on first container start (extensions)
docker-compose.yml  database + Adminer
```

Every module follows the same four-file shape — `models.py` (tables),
`schemas.py` (Pydantic in/out), `service.py` (logic), `__init__.py` — so a new stage
slots in predictably.
