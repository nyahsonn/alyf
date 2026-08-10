"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  api,
  ApiError,
  type ActionPlan,
  type Document,
  type HomeReport,
} from "@/lib/api";
import {
  SYSTEM_LABELS,
  URGENCY_LABELS,
  URGENCY_TIERS,
  CONDITION_TONE,
  confidenceLabel,
  formatCostRange,
} from "@/lib/format";

function ConfidenceGauge({ value }: { value: number }) {
  return (
    <span className="flex items-center gap-1.5" title={`${value.toFixed(2)} confidence`}>
      <span className="h-1.5 w-12 overflow-hidden rounded-full bg-surface-sunk">
        <span
          className="block h-full rounded-full bg-ink-faint"
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </span>
      <span className="text-[11px] font-medium text-ink-faint">{confidenceLabel(value)} confidence</span>
    </span>
  );
}

export default function ReportPage() {
  const params = useParams<{ id: string }>();
  const [document, setDocument] = useState<Document | null>(null);
  const [homeReport, setHomeReport] = useState<HomeReport | null>(null);
  const [actionPlan, setActionPlan] = useState<ActionPlan | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.getDocument(params.id),
      api.getHomeReport(params.id),
      api.getActionPlan(params.id),
    ])
      .then(([document, homeReport, actionPlan]) => {
        setDocument(document);
        setHomeReport(homeReport);
        setActionPlan(actionPlan);
      })
      .catch((caught) =>
        setError(
          caught instanceof ApiError
            ? caught.message
            : "Something went wrong. Check the browser console.",
        ),
      );
  }, [params.id]);

  if (error) {
    return (
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center px-6 py-10 text-center">
        <p className="text-sm text-brick">{error}</p>
        <Link
          href="/upload"
          className="mt-4 text-sm font-medium text-accent underline underline-offset-2"
        >
          Upload another report
        </Link>
      </main>
    );
  }

  if (!document || !homeReport || !actionPlan) {
    return (
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center px-6 py-10 text-center">
        <p className="text-sm text-ink-soft">Loading your report…</p>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-14">
      <Link
        href="/upload"
        className="text-xs font-medium text-ink-faint underline underline-offset-2 hover:text-ink"
      >
        ← Upload another report
      </Link>

      <header className="mt-5 mb-12">
        <h1 className="font-display text-3xl font-medium tracking-tight">
          AI Home Health Report
        </h1>
        <p className="mt-2 text-sm text-ink-soft">{document.title}</p>
        <Link
          href={`/reports/${document.id}/timeline`}
          className="mt-3 inline-block text-xs font-medium text-accent underline underline-offset-2"
        >
          View system timeline →
        </Link>
      </header>

      <section className="mb-12">
        <h2 className="mb-5 text-xs font-semibold tracking-wide text-ink-soft uppercase">
          Systems
        </h2>
        {homeReport.systems.length === 0 ? (
          <p className="text-sm text-ink-soft">No systems found.</p>
        ) : (
          <ul className="space-y-3">
            {homeReport.systems.map((system) => {
              const tone = CONDITION_TONE[system.condition] ?? CONDITION_TONE.not_mentioned;
              return (
                <li
                  key={system.id}
                  className="rounded-2xl border border-line bg-surface px-6 py-5 text-sm"
                >
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="font-medium text-ink">
                      {SYSTEM_LABELS[system.name] ?? system.name}
                    </span>
                    <span
                      className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold tracking-wide uppercase ${tone.pill}`}
                    >
                      {system.condition.replace("_", " ")}
                    </span>
                    <ConfidenceGauge value={system.condition_confidence} />
                    <span className="ml-auto font-mono text-xs tabular-nums text-ink-faint">
                      {system.estimated_age_years !== null
                        ? `${system.estimated_age_years} yrs old`
                        : "age unknown"}
                    </span>
                  </div>
                  {system.findings.length > 0 ? (
                    <ul className="mt-3 list-disc space-y-1 pl-4 text-[13.5px] leading-relaxed text-ink-soft">
                      {system.findings.map((finding, index) => (
                        <li key={index}>{finding}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-3 text-[13.5px] text-ink-faint">No findings noted.</p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section>
        <h2 className="mb-1 text-xs font-semibold tracking-wide text-ink-soft uppercase">
          Action plan
        </h2>
        {actionPlan.items.length === 0 ? (
          <p className="mt-2 text-sm text-ink-soft">No action items yet.</p>
        ) : (
          <>
            <p className="mb-6 text-xs text-ink-faint">
              Prioritized into a 90-day / 2-year / 5-year roadmap, with an
              estimated cost range per item.
            </p>
            <ol className="space-y-8">
              {URGENCY_TIERS.map((tier, index) => {
                const items = actionPlan.items.filter((item) => item.urgency === tier);
                if (items.length === 0) return null;
                return (
                  <li key={tier}>
                    <h3 className="mb-3 flex items-center gap-2.5 text-xs font-semibold tracking-wide text-ink-soft uppercase">
                      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent font-mono text-[11px] font-semibold text-accent-ink">
                        {index + 1}
                      </span>
                      {URGENCY_LABELS[tier]}
                    </h3>
                    <ul className="space-y-3 border-l border-line pl-5">
                      {items.map((item) => (
                        <li
                          key={item.id}
                          className="rounded-2xl border border-line bg-surface px-6 py-5 text-sm"
                        >
                          <div className="flex flex-wrap items-center gap-3">
                            <span className="font-medium text-ink">
                              {SYSTEM_LABELS[item.system] ?? item.system}
                            </span>
                            <span className="ml-auto font-mono text-xs font-semibold tabular-nums text-accent">
                              {formatCostRange(item.cost_low, item.cost_high)}
                            </span>
                          </div>
                          <p className="mt-2 text-[13.5px] leading-relaxed text-ink-soft">
                            {item.recommendation}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </li>
                );
              })}
            </ol>
          </>
        )}
      </section>
    </main>
  );
}
