"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  type Answer,
  type DbHealth,
  type Document,
  type Fact,
  type HomeReport,
  type Report,
} from "@/lib/api";

const SYSTEM_LABELS: Record<string, string> = {
  roof: "Roof",
  hvac: "HVAC",
  plumbing: "Plumbing",
  electrical: "Electrical",
  water_heater: "Water heater",
  foundation: "Foundation",
};

const SAMPLE_TEXT = `Property: 482 Birchwood Lane
Inspection Date: 2026-08-01

Roof: Asphalt shingle, installed in 2016 (approximately 10 years old). Minor
granule loss was observed on the south-facing slope. No active leaks or soft
spots were found. Condition: Good.

HVAC: Central forced-air system, unit manufactured in 2010. The air filter
was heavily soiled and should be replaced immediately. The furnace
short-cycled once during testing -- recommend servicing before the next
heating season. Condition: Fair.

Foundation: Poured concrete. A hairline crack was observed along the north
wall; it appears cosmetic rather than structural, with no signs of water
intrusion. Condition: Good.`;

export default function Home() {
  const [health, setHealth] = useState<DbHealth | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [facts, setFacts] = useState<Fact[]>([]);
  const [homeReport, setHomeReport] = useState<HomeReport | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [report, setReport] = useState<Report | null>(null);

  const [title, setTitle] = useState("482 Birchwood Lane — Inspection");
  const [content, setContent] = useState(SAMPLE_TEXT);
  const [question, setQuestion] = useState("What did the inspector say about the HVAC?");

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  /** Wraps an async action with shared busy/error handling. */
  const run = useCallback(
    async (label: string, action: () => Promise<void>) => {
      setBusy(label);
      setError(null);
      try {
        await action();
      } catch (caught) {
        setError(
          caught instanceof ApiError
            ? caught.message
            : "Something went wrong. Check the browser console.",
        );
      } finally {
        setBusy(null);
      }
    },
    [],
  );

  const refreshDocuments = useCallback(async () => {
    setDocuments(await api.listDocuments());
  }, []);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => setHealth(null));
    refreshDocuments().catch(() => {
      /* surfaced by the connection banner */
    });
  }, [refreshDocuments]);

  const selectDocument = (documentId: string) =>
    run("select", async () => {
      setSelectedId(documentId);
      setAnswer(null);
      setReport(null);
      const [documentFacts, existingHomeReport] = await Promise.all([
        api.listFacts(documentId),
        api.getHomeReport(documentId),
      ]);
      setFacts(documentFacts);
      setHomeReport(existingHomeReport);
    });

  const handleIngest = () =>
    run("ingest", async () => {
      const document = await api.createDocument({ title, content });
      await refreshDocuments();
      setSelectedId(document.id);
      setFacts([]);
      setHomeReport(null);
      setAnswer(null);
      setReport(null);
    });

  const handleUpload = (file: File) =>
    run("upload", async () => {
      const document = await api.uploadDocument(file);
      await refreshDocuments();
      setSelectedId(document.id);
      setFacts([]);
      setHomeReport(null);
      setAnswer(null);
      setReport(null);
    });

  const handleExtract = () =>
    run("extract", async () => {
      if (!selectedId) return;
      const result = await api.extract(selectedId);
      setFacts(result.facts);
      await refreshDocuments();
    });

  const handleHomeReport = () =>
    run("home-report", async () => {
      if (!selectedId) return;
      setHomeReport(await api.createHomeReport(selectedId));
    });

  const handleAsk = () =>
    run("ask", async () => {
      setAnswer(
        await api.ask({
          question,
          document_id: selectedId ?? undefined,
          top_k: 5,
        }),
      );
    });

  const handleReport = () =>
    run("report", async () => {
      if (!selectedId) return;
      setReport(await api.createReport(selectedId));
    });

  const handleDelete = (documentId: string) =>
    run("delete", async () => {
      await api.deleteDocument(documentId);
      if (selectedId === documentId) {
        setSelectedId(null);
        setFacts([]);
        setHomeReport(null);
        setAnswer(null);
        setReport(null);
      }
      await refreshDocuments();
    });

  const selected =
    documents.find((document) => document.id === selectedId) ?? null;

  return (
    <main className="mx-auto w-full max-w-5xl px-6 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight">ALYF</h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
          Ingest → extract → reason → report
        </p>
        <StatusBanner health={health} />
      </header>

      {error && (
        <div
          role="alert"
          className="mb-6 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200"
        >
          {error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <aside className="space-y-3">
          <Card title="1 · Ingest">
            <label className="block text-xs font-medium text-neutral-500">
              Title
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                className="mt-1 w-full rounded-md border border-neutral-300 bg-transparent px-2 py-1.5 text-sm text-neutral-900 dark:border-neutral-700 dark:text-neutral-100"
              />
            </label>
            <label className="mt-3 block text-xs font-medium text-neutral-500">
              Content
              <textarea
                value={content}
                onChange={(event) => setContent(event.target.value)}
                rows={7}
                className="mt-1 w-full resize-y rounded-md border border-neutral-300 bg-transparent px-2 py-1.5 font-mono text-xs text-neutral-900 dark:border-neutral-700 dark:text-neutral-100"
              />
            </label>
            <Button
              onClick={handleIngest}
              loading={busy === "ingest"}
              disabled={!title.trim() || !content.trim()}
            >
              Ingest text
            </Button>
            <input
              ref={fileInput}
              type="file"
              accept=".txt,.md,.csv,.pdf"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) handleUpload(file);
                event.target.value = "";
              }}
            />
            <Button
              variant="ghost"
              onClick={() => fileInput.current?.click()}
              loading={busy === "upload"}
            >
              …or upload a .txt / .md / .pdf file
            </Button>
          </Card>

          <Card title={`Documents (${documents.length})`}>
            {documents.length === 0 ? (
              <p className="text-xs text-neutral-500">Nothing ingested yet.</p>
            ) : (
              <ul className="space-y-1">
                {documents.map((document) => (
                  <li key={document.id} className="flex items-center gap-1">
                    <button
                      onClick={() => selectDocument(document.id)}
                      className={`flex-1 truncate rounded px-2 py-1.5 text-left text-sm transition-colors ${
                        document.id === selectedId
                          ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900"
                          : "hover:bg-neutral-100 dark:hover:bg-neutral-800"
                      }`}
                      title={document.title}
                    >
                      {document.title}
                      <span className="ml-1 text-[10px] opacity-60">
                        {document.status}
                      </span>
                    </button>
                    <button
                      onClick={() => handleDelete(document.id)}
                      aria-label={`Delete ${document.title}`}
                      className="rounded px-1.5 py-1 text-xs text-neutral-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950"
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </aside>

        <section className="space-y-4">
          {!selected ? (
            <Card title="Get started">
              <p className="text-sm text-neutral-500">
                Ingest the sample text on the left, then run extraction, ask a
                question, and generate a report.
              </p>
            </Card>
          ) : (
            <>
              <Card title="2 · Extract">
                <p className="mb-3 text-sm text-neutral-500">
                  Split <strong>{selected.title}</strong> into chunks, pull out
                  facts, and store an embedding for each one in pgvector.
                </p>
                <Button onClick={handleExtract} loading={busy === "extract"}>
                  {facts.length > 0 ? "Re-run extraction" : "Extract facts"}
                </Button>
                {facts.length > 0 && (
                  <ul className="mt-4 max-h-72 space-y-1.5 overflow-y-auto">
                    {facts.map((fact) => (
                      <li
                        key={fact.id}
                        className="rounded-md border border-neutral-200 px-3 py-2 text-xs dark:border-neutral-800"
                      >
                        <div className="flex items-center gap-2">
                          <span className="rounded bg-neutral-100 px-1.5 py-0.5 font-medium text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300">
                            {fact.kind}
                          </span>
                          <span className="font-medium">{fact.label}</span>
                          <span className="ml-auto text-neutral-400">
                            {fact.confidence.toFixed(2)}
                          </span>
                        </div>
                        <p className="mt-1 text-neutral-600 dark:text-neutral-400">
                          {fact.value}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              <Card title="3 · Home Report">
                <p className="mb-3 text-sm text-neutral-500">
                  Send <strong>{selected.title}</strong> to Claude and get
                  back the AI Home Health Report — one entry per system, each
                  with an age, a condition, findings, and a confidence score
                  per field.
                </p>
                <Button
                  onClick={handleHomeReport}
                  loading={busy === "home-report"}
                >
                  {homeReport && homeReport.systems.length > 0
                    ? "Re-generate home report"
                    : "Generate home report"}
                </Button>
                {homeReport && homeReport.systems.length > 0 && (
                  <ul className="mt-4 space-y-2">
                    {homeReport.systems.map((system) => (
                      <li
                        key={system.id}
                        className="rounded-md border border-neutral-200 px-3 py-2 text-xs dark:border-neutral-800"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">
                            {SYSTEM_LABELS[system.name] ?? system.name}
                          </span>
                          <span className="rounded bg-neutral-100 px-1.5 py-0.5 font-medium text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300">
                            {system.condition}
                          </span>
                          <span className="text-neutral-400">
                            ({system.condition_confidence.toFixed(2)})
                          </span>
                          <span className="ml-auto text-neutral-500">
                            {system.estimated_age_years !== null
                              ? `${system.estimated_age_years} yrs`
                              : "age unknown"}{" "}
                            <span className="text-neutral-400">
                              ({system.estimated_age_confidence.toFixed(2)})
                            </span>
                          </span>
                        </div>
                        {system.findings.length > 0 ? (
                          <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-neutral-600 dark:text-neutral-400">
                            {system.findings.map((finding, index) => (
                              <li key={index}>{finding}</li>
                            ))}
                          </ul>
                        ) : (
                          <p className="mt-1.5 text-neutral-400">
                            No findings noted.
                          </p>
                        )}
                        <p className="mt-1 text-[10px] text-neutral-400">
                          findings confidence{" "}
                          {system.findings_confidence.toFixed(2)}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              <Card title="4 · Reason">
                <div className="flex gap-2">
                  <input
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && question.trim().length >= 3) {
                        handleAsk();
                      }
                    }}
                    placeholder="Ask a question about this document"
                    className="flex-1 rounded-md border border-neutral-300 bg-transparent px-3 py-2 text-sm dark:border-neutral-700"
                  />
                  <Button
                    inline
                    onClick={handleAsk}
                    loading={busy === "ask"}
                    disabled={question.trim().length < 3}
                  >
                    Ask
                  </Button>
                </div>
                {answer && (
                  <div className="mt-4">
                    <pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-neutral-50 p-3 font-mono text-xs dark:bg-neutral-900">
                      {answer.answer}
                    </pre>
                    {answer.evidence.length > 0 && (
                      <p className="mt-2 text-xs text-neutral-500">
                        Matched {answer.evidence.length} fact
                        {answer.evidence.length === 1 ? "" : "s"} by vector
                        similarity (top score{" "}
                        {answer.evidence[0].score.toFixed(3)}).
                      </p>
                    )}
                  </div>
                )}
              </Card>

              <Card title="5 · Report">
                <Button onClick={handleReport} loading={busy === "report"}>
                  Generate report
                </Button>
                {report && (
                  <div className="mt-4">
                    <p className="text-sm font-medium">{report.title}</p>
                    <p className="mt-1 text-xs text-neutral-500">
                      {report.fact_count} facts included
                    </p>
                    <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-neutral-50 p-3 font-mono text-xs dark:bg-neutral-900">
                      {report.body_markdown}
                    </pre>
                  </div>
                )}
              </Card>
            </>
          )}
        </section>
      </div>
    </main>
  );
}

function StatusBanner({ health }: { health: DbHealth | null }) {
  if (health) {
    return (
      <p className="mt-3 text-xs text-neutral-500">
        <span className="mr-1.5 inline-block h-2 w-2 rounded-full bg-emerald-500 align-middle" />
        Backend connected · pgvector {health.pgvector} ·{" "}
        {health.embedding_dimensions}-dim embeddings
      </p>
    );
  }
  return (
    <p className="mt-3 text-xs text-amber-700 dark:text-amber-500">
      <span className="mr-1.5 inline-block h-2 w-2 rounded-full bg-amber-500 align-middle" />
      Backend not reachable. Start the database and API — see the README.
    </p>
  );
}

function Card({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-neutral-200 p-4 dark:border-neutral-800">
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      {children}
    </div>
  );
}

function Button({
  children,
  onClick,
  loading = false,
  disabled = false,
  variant = "solid",
  inline = false,
}: {
  children: React.ReactNode;
  onClick: () => void;
  loading?: boolean;
  disabled?: boolean;
  variant?: "solid" | "ghost";
  /** Inline buttons sit beside an input instead of stacking full-width. */
  inline?: boolean;
}) {
  const base = `rounded-md px-3 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
    inline ? "shrink-0" : "mt-3 w-full"
  }`;
  const styles =
    variant === "solid"
      ? "bg-neutral-900 text-white hover:bg-neutral-700 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
      : "border border-neutral-300 text-neutral-600 hover:bg-neutral-100 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800";

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || loading}
      className={`${base} ${styles}`}
    >
      {loading ? "Working…" : children}
    </button>
  );
}
