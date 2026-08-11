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
`reports` was originally the only stage that read across the others; `reasoning` and
`notifications` now do too, both for the same reason — scoping a query to the logged-in
inspector's own data (see [Inspector accounts](#inspector-accounts)) requires joining
out to `ingestion`'s `documents` table.

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

The UI is at http://localhost:3000 — that's the public landing page; sign up, then
try the real product at `/upload`. The original generic-pipeline test harness
(ingest a document, extract facts, ask questions, generate a Markdown report, with a
banner showing backend and database health) has moved to `/dev`.

### Try it with the sample

`data/samples/sample-inspection-report.md` is a short home inspection report covering
the six systems ALYF tracks, written in the shape the rule-based extractor also
recognises (`Label: value` lines plus prose with figures). Sign up in the UI at
http://localhost:3000, then paste it in — or, from the command line, sign up first
(every route below needs a logged-in inspector — see
[Inspector accounts](#inspector-accounts)) and reuse the session cookie:

```bash
curl -c cookies.txt -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "at-least-8-characters"}'

curl -b cookies.txt -F "file=@data/samples/sample-inspection-report.md" \
  http://localhost:8000/api/v1/documents/upload
```

Then, using the returned document id (keep passing `-b cookies.txt`):

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
| `POST`   | `/auth/signup`                  | Create an inspector account, sets the session cookie |
| `POST`   | `/auth/login`                   | Sets the session cookie                        |
| `POST`   | `/auth/logout`                  | Clears the session cookie                      |
| `GET`    | `/auth/me`                      | The logged-in inspector                        |
| `GET`    | `/auth/google/login`            | Redirects to Google; sets the session cookie on return (see [Sign in with Google](#sign-in-with-google)) |
| `GET`    | `/auth/google/callback`         | Google's redirect target — not called directly |
| `POST`   | `/documents`                    | Ingest a document from a JSON body             |
| `POST`   | `/documents/upload`             | Ingest an uploaded file — PDFs are OCR'd first |
| `GET`    | `/documents`                    | List **your own** documents                    |
| `GET`    | `/documents/{id}`               | Document detail, including its chunks          |
| `DELETE` | `/documents/{id}`               | Delete a document and everything derived from it |
| `DELETE` | `/documents/{id}/notify-email`  | Unsubscribe — clears `notify_email` (see [Weekly roadmap reminders](#weekly-roadmap-reminders)) |
| `POST`   | `/documents/{id}/extract`       | Extract and embed facts for a document         |
| `GET`    | `/facts`                        | A document's extracted facts (`document_id` required) |
| `POST`   | `/documents/{id}/home-report`   | Generate the AI Home Health Report via Claude  |
| `GET`    | `/documents/{id}/home-report`   | The most recently generated home report, if any |
| `POST`   | `/documents/{id}/action-plan`   | Generate a prioritized action plan via Claude  |
| `GET`    | `/documents/{id}/action-plan`   | The most recently generated action plan, if any |
| `GET`    | `/documents/{id}/status`        | The report's review status (see [Review and approval](#review-and-approval)) |
| `POST`   | `/documents/{id}/approve`       | Inspector sign-off — unlocks the report at its public link |
| `PATCH`  | `/documents/{id}/findings/{finding_id}` | Edit a finding's wording during review |
| `PATCH`  | `/documents/{id}/action-items/{item_id}` | Edit an action item's urgency tier and/or recommendation during review |
| `GET`    | `/documents/{id}/buyer-report`  | The public, unauthenticated report a buyer sees at its link |
| `POST`   | `/ask`                          | Vector-search **your own** facts and compose an answer |
| `GET`    | `/insights`                     | List **your own** past questions and their answers |
| `POST`   | `/reports`                      | Generate a Markdown report for a document      |
| `GET`    | `/reports`                      | List **your own** reports                      |
| `GET`    | `/reports/{id}`                 | Report detail, including rendered Markdown     |

`POST /documents/upload` also accepts an optional `notify_email` form field, which
opts that document into the weekly roadmap reminder job — see
[Weekly roadmap reminders](#weekly-roadmap-reminders).

Every route above except `/health*`, `/auth/signup`, `/auth/login`, the
unsubscribe route, and `/documents/{id}/buyer-report` requires a logged-in
inspector (see [Inspector accounts](#inspector-accounts)) and only ever
operates on that inspector's own data — a document, report, or insight
belonging to someone else returns `404`, the same response as one that
doesn't exist at all. `/documents/{id}/buyer-report` shares the unsubscribe
route's trust model instead — an unguessable id, no login, since homeowners
don't have inspector accounts — and additionally withholds every field but
`status` until the report is out of `pending_review` (see
[Review and approval](#review-and-approval)).

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
| `RESEND_API_KEY`       | —                                                    | Needed by `scripts/send_roadmap_reminders.py` — see [Weekly roadmap reminders](#weekly-roadmap-reminders) |
| `RESEND_FROM_EMAIL`    | `onboarding@resend.dev`                              | Resend's sandbox sender; works with no domain verification |
| `FRONTEND_BASE_URL`    | `http://localhost:3000`                              | Used to build the report link inside reminder emails |
| `AUTO_SEND_AFTER_HOURS` | `36`                                                | How long a report can sit at `pending_review` before `scripts/auto_send_pending_reports.py` moves it to `auto_sent` on its own — see [Review and approval](#review-and-approval) |
| `JWT_SECRET`           | a working local placeholder                          | **Change this in any real deployment** — see [Inspector accounts](#inspector-accounts) |
| `JWT_EXPIRES_DAYS`     | `14`                                                 | Session length                                 |
| `AUTH_COOKIE_NAME`     | `alyf_session`                                       | Also hardcoded in `frontend/src/proxy.ts` — keep the two in sync if you change it |
| `COOKIE_SECURE`        | `false`                                              | Set `true` once served over `https://`         |
| `SESSION_SECRET`       | a working local placeholder                          | Backs Starlette's `SessionMiddleware` — separate from `JWT_SECRET`, see [Sign in with Google](#sign-in-with-google) |
| `BACKEND_BASE_URL`     | `http://localhost:8000`                              | Used to build the Google OAuth callback URL    |
| `GOOGLE_CLIENT_ID`     | —                                                    | From Google Cloud Console — see [Sign in with Google](#sign-in-with-google) |
| `GOOGLE_CLIENT_SECRET` | —                                                    | From Google Cloud Console                      |
| `SENTRY_DSN`           | —                                                    | From a Sentry project — see [Error monitoring](#error-monitoring) |

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
| `NEXT_PUBLIC_SENTRY_DSN` | — | From a **separate** Sentry project than the backend's — see [Error monitoring](#error-monitoring) |

## Inspector accounts

Every home inspector has their own account (email + password) and only ever sees
their own documents, reports, and homes — the whole product's premise is that a
report belongs to the inspector who ran it, so this isn't optional multi-tenancy
bolted on later.

**How it works:** `POST /auth/signup` / `POST /auth/login` hash the password with
`bcrypt` and set a `PyJWT`-signed session in an httpOnly cookie
(`app/auth/service.py`). `GET /auth/me` and every document-scoped route read that
cookie via `CurrentInspectorDep` (`app/api/deps.py`) — missing, tampered, or expired
all fail the same way, a `401`. Most document-scoped routes go through
`OwnedDocumentDep`, which does the existence-and-ownership check in one place and
returns `404` (not `403`) on a mismatch, so a request can never distinguish "this
document doesn't exist" from "it exists but isn't yours."

**`Home` is scoped too, not just `Document`.** Two different inspectors reporting on
the same physical address would otherwise resolve to the same `Home` row (matched
purely by normalized address — see `_resolve_home` in `extraction/service.py`) and
each would see the other's findings through that collision. `Home.inspector_id` is
part of the match specifically to prevent that.

**Frontend:** `/login`, `/signup`, and the public landing page at `/` are the only
pages reachable without a session; `/dev` (a leftover test harness for the original
generic ingest/extract/reason/report pipeline, not the AI Home Health Report product
itself) and `/upload` both check `GET /auth/me` on load and redirect
to `/login` on `401`, backed up by `frontend/src/proxy.ts`, which redirects on the
session cookie's absence before the page even loads — a UX shortcut, not the real
security boundary, since it only checks the cookie is *present*, not that it's
valid. **`/reports/*` is deliberately excluded from all of this** — homeowners don't
have inspector accounts, so the report, timeline, and unsubscribe pages support
unauthenticated, link-based access too. Concretely, the report and timeline pages try
the authenticated, owned-document routes first and fall back to the public
`GET /documents/{id}/buyer-report` route when that fails (not logged in, or logged in
as someone else) — see [Review and approval](#review-and-approval) for the full
inspector-vs-buyer split, including the review gate that route enforces.

Explicit non-goals for now: no email verification, no forgot-password flow, no
rate-limiting or lockout on failed logins, no roles or admin view. CSRF is handled by
`SameSite=Lax` on the session cookie (blocks it on cross-site `POST`/`DELETE`, the
actual attack surface) rather than a separate CSRF token.

Existing rows from before accounts existed have `inspector_id IS NULL` — not deleted,
not reassigned, just invisible to every inspector-scoped list/lookup from now on. As
with `notify_email` before it, adding a column to an already-running local database
needs a manual step, since there's no migration framework in this project:

```sql
ALTER TABLE documents ADD COLUMN inspector_id UUID REFERENCES inspectors(id) ON DELETE SET NULL;
ALTER TABLE homes ADD COLUMN inspector_id UUID REFERENCES inspectors(id) ON DELETE SET NULL;
ALTER TABLE insights ADD COLUMN inspector_id UUID REFERENCES inspectors(id) ON DELETE SET NULL;

CREATE INDEX ix_documents_inspector_id ON documents(inspector_id);
CREATE INDEX ix_homes_inspector_id ON homes(inspector_id);
CREATE INDEX ix_insights_inspector_id ON insights(inspector_id);
```

Run this **after** the backend has started at least once with the new code (the
`inspectors` table the `REFERENCES` above points at doesn't exist until then).

`inspectors` itself is a brand-new table, created automatically on restart, same as
`reminder_logs` before it.

### Sign in with Google

"Continue with Google" is an additional, equally-first-class way in — not a
replacement for email + password, which stays exactly as it is. It uses
[`authlib`](https://docs.authlib.org/) (`app/auth/oauth.py`), the standard
OAuth/OIDC client for Starlette/FastAPI: Google publishes an OpenID Connect
discovery document, so authlib fetches its public keys and verifies the signed
`id_token` itself — there's no hand-rolled JWT verification in this codebase.

**Setup:** register an OAuth 2.0 Client ID in the
[Google Cloud Console](https://console.cloud.google.com/apis/credentials) (Web
application type), add `{BACKEND_BASE_URL}/api/v1/auth/google/callback` (e.g.
`http://localhost:8000/api/v1/auth/google/callback` locally) as an authorized
redirect URI, and put the resulting client ID/secret in `backend/.env` as
`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`. Left blank, `GET
/auth/google/login` returns a clear "Google sign-in isn't configured yet."
`400` instead of redirecting to Google with an empty client ID.

**Account linking** (`find_or_create_from_oauth` in `app/auth/service.py`):
1. An existing `OAuthAccount` for this exact Google user ID → that inspector.
2. Otherwise, **only if Google reports the email as verified**, an existing
   password-based inspector with that email → link Google onto that same
   account rather than creating a second one. This verified-email check is the
   one real security-relevant piece of this feature — auto-linking on an
   *unverified* email would let anyone who controls some Google-adjacent
   identity claim an existing account.
3. Otherwise, create a new inspector with `password_hash = NULL` — an
   OAuth-only account has no password, and a password-login attempt against it
   fails cleanly (`authenticate()` short-circuits on a `NULL` hash rather than
   passing `None` into `bcrypt.checkpw`).

`oauth_accounts` is a new table, created automatically like `inspectors` was.
`inspectors.password_hash` needs an actual constraint change on an
already-running local database, not just a new column:

```sql
ALTER TABLE inspectors ALTER COLUMN password_hash DROP NOT NULL;
```

**Frontend:** `/login` and `/signup` both show a "Continue with Google" button
— a real `<a>` tag pointing at `GET /auth/google/login`, not `fetch`, since the
flow needs a full browser navigation for Google's own login screen to appear.
`GET /auth/google/callback` redirects back to `{FRONTEND_BASE_URL}/upload` on
success (setting the same session cookie password login does) or to
`{FRONTEND_BASE_URL}/login?error=...` on failure, which `/login` reads and
shows in its existing error-banner.

## Error monitoring

### Backend

Three request paths call out to something that can fail for reasons entirely
outside ALYF's control: Document AI (OCR on upload), and Claude (home-report
and action-plan generation). All three already catch that failure and turn it
into a clean `502` for the caller (`app/api/routes/ingestion.py`,
`app/api/routes/extraction.py`) — but until now, the only record of *why* was
a `logger.error` line in a server log nobody is watching in real time. This
wires those same three catch blocks to [Sentry](https://sentry.io) as well, so
a real failure pages someone instead of surfacing "days later."

**Setup** (you'll need to do this part — creating the account is not something
this assistant can do on your behalf):
1. Sign up at [sentry.io](https://sentry.io) (free tier is enough for this) and
   create a Python/FastAPI project.
2. Copy its DSN into `backend/.env` as `SENTRY_DSN`. Left blank,
   `sentry_sdk.init` is never called (see `app/main.py`) — the app behaves
   exactly as it does today, just without alerting.
3. **Email alerts work with no further setup** — every new Sentry project ships
   with a default alert rule that emails project members on a new issue.
4. **Slack alerts** need one extra one-time step in the Sentry dashboard, not
   in this codebase: *Settings → Integrations → Slack* to connect your
   workspace, then add a "Send a Slack notification" action to the project's
   alert rule (*Alerts → your rule → Actions*). Sentry's own docs walk through
   this; it's an OAuth authorization against your Slack workspace, so it has to
   be you clicking through it, not code shipped here.

**How it's wired:** `app/main.py` calls `sentry_sdk.init(dsn=..., environment=...)`
once at startup if `SENTRY_DSN` is set — no `traces_sample_rate`, since this is
error monitoring, not performance tracing, so every captured exception is sent,
none sampled away. FastAPI/Starlette are auto-instrumented by `sentry_sdk`
whenever it detects those packages, so genuinely unhandled exceptions anywhere
in a request are already captured without further code. The three sites above
are different: they *handle* their exception (to return a clean `502` instead
of a raw 500), which is exactly what stops Sentry's automatic capture from ever
seeing them — each one now also calls `sentry_sdk.capture_exception(e)` inside
a scope tagged with `document_id` (or the upload's filename, before a document
exists yet) and which stage failed, so the alert says *which report* broke, not
just that something did.

### Frontend

A **separate** Sentry project from the backend's — mixing a Next.js hydration
error and a Claude API failure into one project's issue stream makes both
harder to read, and the two apps fail independently of each other anyway.

**Setup:**
1. In the same Sentry organization, create a second project — platform
   **Next.js** this time.
2. Copy its DSN into `frontend/.env.local` as `NEXT_PUBLIC_SENTRY_DSN`. The
   `NEXT_PUBLIC_` prefix is correct here, not a mistake — a DSN is meant to
   ship inside client-side bundles (that's how the browser reports its own
   errors), unlike an actual secret. Left blank, `Sentry.init` still runs but
   has nothing to send to.
3. Same email-by-default / Slack-needs-one-step story as the backend project
   above — it's a separate project, so it needs its own alert rule looked at
   if you want Slack there too.

**How it's wired:** `@sentry/nextjs` needs three things: `frontend/src/instrumentation.ts`
(Next.js's own hook, not Sentry-specific — `register()` runs once per server
runtime and initializes Sentry for it; `onRequestError` captures server-side
request errors), `frontend/src/instrumentation-client.ts` (same idea for the
browser — this exact filename is a Next.js convention Sentry's build plugin
looks for), and `next.config.ts` wrapped in `withSentryConfig`. No
`org`/`project`/`authToken` are set on that last one, so source maps are never
uploaded — captured errors show minified stack traces rather than readable
ones, which is fine for "did this break" alerting but not for reading exactly
which line failed. Add those three (from Sentry's project settings) once you
want symbolicated traces; nothing else about the setup changes.

## Weekly roadmap reminders

`scripts/send_roadmap_reminders.py` checks every document that opted in (via
`notify_email` at upload time, see [API](#api)) for outstanding action-plan items in
the `next_90_days` tier, and sends one short, plain-language email per document that
has anything outstanding — never one per item, and never an "all clear" email when
there's nothing to report.

**Reminders ramp up, not flat weekly.** How often a document gets re-emailed depends
on how close its soonest outstanding item is to its 90-day mark: roughly monthly
while there's no real urgency, roughly weekly once inside the final 30 days
(`app/notifications/service.py`'s `reminder_interval_days`) — including once an item
is overdue, which is just a very negative days-until-due, still inside that same
weekly branch. Run the script on any schedule you like (weekly is a safe default);
it only actually sends when a document's own cadence says today is due, tracked in
the `reminder_logs` table (one row per document, the timestamp of its last send).

```bash
cd backend
python scripts/send_roadmap_reminders.py --dry-run   # prints each email instead of sending
python scripts/send_roadmap_reminders.py              # sends for real — needs RESEND_API_KEY
```

Sign up at [resend.com](https://resend.com/signup) (free, no card required) and put
an API key in `backend/.env` as `RESEND_API_KEY`. The default sender,
`onboarding@resend.dev`, is Resend's own sandbox address and works immediately with
no domain verification — switch `RESEND_FROM_EMAIL` once you've verified your own
domain.

**This is a script, not a scheduled job** — there is no scheduler running inside the
app, and none is set up here, since there's nowhere for one to run yet (the only
deployment target today is `docker compose` for local Postgres). Once the backend is
actually deployed somewhere, point that platform's cron / scheduled-task feature (or
plain `cron`, or Windows Task Scheduler for a machine that's always on) at the command
above — anywhere from daily to weekly is fine, since the cadence logic above decides
per document whether today is actually a send day.

Every reminder email ends with an unsubscribe link
(`DELETE /documents/{id}/notify-email`, fronted by `/reports/{id}/unsubscribe` in the
frontend) that clears `notify_email` for that document — the release valve for an
item that stays overdue indefinitely, since there's no "mark resolved" concept (see
below) to know when it's safe to stop on its own. No login is needed to use it: same
trust model as the report link itself (an unguessable id, no auth system exists yet).

Two things worth knowing before relying on this:

- **`created_at`, not an inspection date, anchors the 90-day window.** `InspectionEvent.inspection_date` exists in the schema but is never populated by the pipeline
  today (see `app/extraction/models.py`), so "due" is measured from when the action
  plan was generated, not from the actual inspection.
- **There's no way to mark an item resolved**, only a way to stop hearing about all of
  them at once via unsubscribe. A homeowner who fixes one thing but wants to keep
  hearing about the rest has no in-between option today; a real "mark as done" flow
  is a separate feature.

If `backend/.env` didn't exist yet when `notify_email` was added to the `documents`
table, a database that was already running needs one manual schema update — there's
no migration framework in this project (see `init_db()` in
`app/core/database.py`):

```sql
ALTER TABLE documents ADD COLUMN notify_email VARCHAR(320);
```

(Or, for a local dev database with nothing worth keeping, `docker compose down -v`
and `docker compose up -d` to rebuild it from scratch instead.) The new
`reminder_logs` table needs no such step — it's a table `create_all` has never seen
before, so a normal backend restart creates it.

## Review and approval

An AI-generated finding, urgency, or cost estimate is a draft until an inspector has
looked at it — nothing reaches a buyer un-reviewed. `InspectionEvent.status` (one row
per document, see `app/extraction/models.py`) tracks this: `pending_review` (set the
moment the home report + action plan are generated) → `approved` (the inspector
reviewed it, via `POST /documents/{id}/approve`) or `auto_sent` (the inspector never
acted within the auto-send window — see below). There's no separate manual "send"
step beyond that: this product has no send-to-buyer email flow today, so both
terminal states mean the same thing to a buyer — the report is now visible at its
link, `GET /documents/{id}/buyer-report`.

**Inspector review.** `/reports/{id}` in the frontend tries the authenticated,
owned-document routes first (`GET /documents/{id}`, `.../home-report`,
`.../action-plan`, plus the new `.../status`); success means the viewer is the
report's own inspector, and the page renders in review mode — inline edit controls
on each finding's wording and each action item's urgency tier/recommendation
(`PATCH .../findings/{id}`, `PATCH .../action-items/{id}`, text-only, no add/delete),
a status badge, and an "Approve for buyer" button. Cost estimates are not editable
here and not part of what approval covers — see
[Going from offline to real models](#going-from-offline-to-real-models) for where
cost comes from.

**Buyer view.** The same `/reports/{id}` page falls back to
`GET /documents/{id}/buyer-report` — no `OwnedDocumentDep`, same unguessable-link
trust model as the unsubscribe route — whenever the authenticated calls fail (not
logged in, or logged in as a different inspector). That endpoint withholds every
field but `status` while a report is `pending_review`; the frontend shows a short
"still being reviewed" holding page instead of findings/costs in that case. This is
the actual liability boundary the whole review gate exists to enforce, and it's
enforced there — `app/extraction/service.py`'s `get_buyer_report` — not trusted to
the frontend to withhold.

**Auto-send fallback**, so a slow inspector doesn't block delivery:

```bash
cd backend
python scripts/auto_send_pending_reports.py --dry-run   # counts without changing anything
python scripts/auto_send_pending_reports.py              # moves stale reports to auto_sent
```

Same "script, not a scheduled job" story as the weekly reminder script above — point
your platform's cron / scheduled-task feature at it, run it more often than the
window itself (e.g. hourly) so a report doesn't sit auto-sendable for long before a
run actually picks it up. The window is `AUTO_SEND_AFTER_HOURS` (default `36`, the
midpoint of a 24–48h target). No email is sent by this script — it only changes a
report's status; the weekly reminder job is what actually emails anything, and (see
below) only once a report is `approved` or `auto_sent`.

**The weekly reminder job never reaches into an unreviewed report.**
`send_weekly_reminders` now skips any document whose event isn't `approved` or
`auto_sent` before it ever calls `get_action_plan` for it — see
`app/notifications/service.py` and `is_report_visible` in
`app/extraction/service.py`.

An already-running local database needs the same kind of manual schema update as
`notify_email` before it:

```sql
ALTER TABLE events ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'pending_review';
ALTER TABLE events ADD COLUMN reviewed_at TIMESTAMPTZ;
ALTER TABLE action_items ADD COLUMN cost_source VARCHAR(30) NOT NULL DEFAULT 'ai_estimated';
```

`cost_source` is set in code (`create_action_plan`) as `"ai_estimated"` — never asked
of Claude. It's the seam a real pricing API (e.g. RSMeans) swaps into later without
another schema change: persist a different value there once `cost_low`/`cost_high`
come from that source instead.

## Disclaimers

Two disclaimers, both placeholder copy — **not legal advice, flag for real legal
review before launch**:

- **Cost disclaimer** (`COST_DISCLAIMER` in `frontend/src/lib/format.ts`, and its own
  copy in `app/notifications/service.py` for the reminder email — Python and
  TypeScript can't share a constant): attached directly next to every cost
  estimate's own block on the report/timeline pages, and next to the cost figures in
  the weekly reminder email. Deliberately not a single disclaimer at the top or
  bottom of the page — proximity to the figure it qualifies is what actually gets
  read.
- **General report disclaimer** (`reportDisclaimer` in the same file): once, near the
  top of the report and timeline pages, naming the inspector by `inspector_name`
  where available (falls back to "your inspector" otherwise — see
  [Review and approval](#review-and-approval) for where that name comes from).

## Tests

68 unit tests cover chunking, the rule-based extractor, dedupe, answer composition,
embedding, PDF/table handling, and (`test_notifications.py`) the weekly roadmap
reminder logic — the escalating reminder cadence, the safety-hazard keyword check,
and the email wording (including the cost disclaimer, see
[Disclaimers](#disclaimers)). They exercise pure functions only, so no database or
running server is needed. The review/approval workflow's own logic
(`approve_event`, `auto_send_stale_events`, `is_report_visible`, and friends in
`app/extraction/service.py`) is not covered here, since it's DB-backed and this repo
has no DB-fixture test setup yet — exercise it against a real database instead (see
[Review and approval](#review-and-approval)'s scripts, or the frontend flow directly).

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
    api/            route definitions + auth/ownership deps, aggregated in router.py
    core/           config, database engine, embeddings
    auth/           inspector accounts  models / schemas / service / oauth.py (Google)
    ingestion/      chunking            models / schemas / service
    extraction/     facts + embeddings  models / schemas / service
    reasoning/      vector search       models / schemas / service
    reports/        Markdown assembly   models / schemas / service
    notifications/  roadmap reminders   emailer / models (reminder_logs only) / service
    main.py         app factory, CORS, startup schema creation
  scripts/          one-off / periodic scripts run outside the API process
  tests/
frontend/
  src/app/          Next.js App Router pages
  src/proxy.ts      redirects to /login if the session cookie is absent
  src/lib/api.ts    typed client for the backend
  src/instrumentation.ts         Sentry init, server/edge runtimes
  src/instrumentation-client.ts  Sentry init, browser
data/samples/       example input documents
db/init/            SQL run on first container start (extensions)
docker-compose.yml  database + Adminer
```

Every data-owning module follows the same four-file shape — `models.py` (tables),
`schemas.py` (Pydantic in/out), `service.py` (logic), `__init__.py` — so a new stage
slots in predictably. `notifications` is a partial exception: besides its own
`reminder_logs` table (cadence bookkeeping, see [Weekly roadmap reminders](#weekly-roadmap-reminders)),
it also reads across `ingestion` and `extraction` through their service functions,
the same role `reports` plays for the request/response pipeline — and has no
`schemas.py`, since nothing it owns is ever returned from an API route.
