# ALYF — frontend

The Next.js UI for ALYF. **See the [root README](../README.md)** for the project
overview, architecture, and full setup — this file covers only what is specific to
this directory.

The frontend is a thin client: it renders the pipeline and calls the FastAPI backend.
All logic lives server-side, so **the backend and database must be running** or the UI
will load with a red health banner and no data. The root README's Quickstart starts
those first, in order.

## Running

```bash
cp .env.local.example .env.local   # PowerShell: Copy-Item .env.local.example .env.local
npm install
npm run dev
```

Then open http://localhost:3000.

| Script          | Purpose                                 |
| --------------- | --------------------------------------- |
| `npm run dev`   | Development server with hot reload      |
| `npm run build` | Production build                        |
| `npm run start` | Serve a production build                |
| `npm run lint`  | ESLint (`eslint-config-next`)           |

## Configuration

One variable, in `.env.local`:

| Variable              | Default                 | Notes                                                             |
| --------------------- | ----------------------- | ----------------------------------------------------------------- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend origin. `NEXT_PUBLIC_` values are inlined into the browser bundle at build time — never put secrets here. |

The `/api/v1` prefix is added by the client, so set this to the origin only. If you
changed the backend's port, change it here too — and make sure the new frontend origin
is listed in `CORS_ORIGINS` in `backend/.env`.

## Layout

```
src/app/layout.tsx    Root layout; loads Geist via next/font/google
src/app/page.tsx      The entire UI — ingest, extract, ask, report
src/app/globals.css   Tailwind v4 theme (configured in CSS, no tailwind.config)
src/lib/api.ts        Typed fetch client; mirrors the backend's Pydantic schemas
```

When you change a backend schema, update the matching type in `src/lib/api.ts` — the
two are kept in sync by hand.

## A note on the Next.js version

This project is on Next.js 16, which differs from earlier versions in ways that trip up
generated code (see `AGENTS.md` in this directory). The authoritative docs for the
pinned version ship inside the package, at `node_modules/next/dist/docs/` — prefer them
over web results when they disagree.
