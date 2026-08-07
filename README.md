# ALYF

A document-understanding pipeline. Raw source material goes in; structured facts,
answers backed by evidence, and Markdown reports come out.

ALYF is built as a **modular monolith** — one deployable backend, four modules with
clear seams between them. Documents flow through the stages in order:

```
ingestion  ->  extraction  ->  reasoning  ->  reports
  chunk         facts +         vector        assemble
  text          embeddings      search        Markdown
```

Each module owns its own tables, schemas, and service functions, and talks to its
neighbours only through service calls — never by querying another module's tables.
`reports` is the only stage that reads across the others.

**It runs entirely offline.** No API keys, no model downloads. The embedder is a
deterministic hashing embedder and the extractor is rule-based, so you can stand the
whole thing up — including real pgvector similarity search inside PostgreSQL — and
watch data move end to end. Both are designed to be swapped for an LLM later; see
[Going from offline to real models](#going-from-offline-to-real-models).

The one exception is [uploading a PDF](#pdfs), which calls out to Google Document AI
for OCR. Text uploads, and every stage after ingestion, still need no credentials.

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

`data/samples/quarterly-update.md` is a small operations update with the shape the
rule-based extractor recognises (`Label: value` lines plus prose with figures). Paste
it into the UI, or upload it directly:

```bash
curl -F "file=@data/samples/quarterly-update.md" http://localhost:8000/api/v1/documents/upload
```

Then extract facts from the returned document id, and ask something like
*"what happened to revenue?"*

### PDFs

`POST /documents/upload` recognises a PDF from its own bytes — not the filename or
the browser's content type — and sends it to Google Document AI for OCR. Everything
else must be UTF-8 text, and is rejected with a `415` if it is not. Documents that
arrive this way are stored with `source_type: "pdf"`.

Point `DOCAI_PROCESSOR_ID` at a **Form Parser** processor. A plain Document OCR
processor returns text alone, and tables are the reason to use OCR at all: Document
AI flattens a table into one cell per line, which loses the link between a number and
the row and column it came from. The table regions are cut out of that text and
re-emitted as `Label: value` lines instead, which is the shape the rule-based
extractor reads — so `Revenue Q2: 5.1M` becomes a fact, rather than the whole page
becoming one unusable claim.

Two limits come from the synchronous Document AI call: 15 pages and 20 MB. A file over
the size limit is rejected with a `413` before anything is sent; larger files need
batch processing, which is a different API.

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

Document AI also needs `GOOGLE_APPLICATION_CREDENTIALS` pointing at a service account
key file. That one is read from the real environment by the Google auth library, not
from `backend/.env`. Only PDF uploads use any of this.

Chunking is tunable in `backend/app/core/config.py` — `chunk_size_words` (180) and
`chunk_overlap_words` (30).

**`frontend/.env.local`**

| Variable              | Default                 | Notes                                                    |
| --------------------- | ----------------------- | -------------------------------------------------------- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | `NEXT_PUBLIC_` values ship in the browser bundle — no secrets |

## Tests

Twenty-eight unit tests cover chunking (4), the rule-based extractor (5), dedupe (6),
answer composition (4), embedding (3), and PDF/table handling (6). They exercise pure
functions only, so no database or running server is needed:

```bash
cd backend
pytest
```

Ruff is configured in `backend/pyproject.toml` (line length 100, rules `E,F,I,UP,B`)
but is intentionally not a pinned dependency — install it however you prefer:

```bash
pip install ruff   # or: uvx ruff check .
ruff check .
```

## Going from offline to real models

Two seams are deliberately naive so the system runs with zero setup. Each is a single
function, and swapping either leaves persistence, dedupe, and retrieval untouched.

- **Embeddings** — `backend/app/core/embeddings.py`. `embed_text` hashes tokens and
  word pairs into a unit-length vector. It is deterministic but not semantically
  meaningful: similarity reflects shared wording, not shared meaning. Replace the body
  with a provider call, set `EMBEDDING_DIMENSIONS` to that model's dimension, and
  recreate the `facts` table (the vector column is fixed-width).
- **Extraction** — `backend/app/extraction/service.py`. `extract_candidates` uses
  regex to find `Label: value` pairs and figures in prose. Replace it with an LLM call
  returning the same candidate shape.
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
