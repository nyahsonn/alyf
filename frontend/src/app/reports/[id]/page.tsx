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
import { SYSTEM_LABELS, URGENCY_LABELS, URGENCY_TIERS, formatCostRange } from "@/lib/format";

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
        <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
        <Link
          href="/upload"
          className="mt-4 text-sm font-medium underline underline-offset-2"
        >
          Upload another report
        </Link>
      </main>
    );
  }

  if (!document || !homeReport || !actionPlan) {
    return (
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center px-6 py-10 text-center">
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          Loading your report…
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-10">
      <Link
        href="/upload"
        className="text-xs font-medium text-neutral-500 underline underline-offset-2 hover:text-neutral-700 dark:hover:text-neutral-300"
      >
        ← Upload another report
      </Link>

      <header className="mt-4 mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">
          AI Home Health Report
        </h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
          {document.title}
        </p>
      </header>

      <section className="mb-8">
        <h2 className="mb-3 text-sm font-semibold">Systems</h2>
        {homeReport.systems.length === 0 ? (
          <p className="text-sm text-neutral-500">No systems found.</p>
        ) : (
          <ul className="space-y-2">
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
                  <p className="mt-1.5 text-neutral-400">No findings noted.</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="mb-1 text-sm font-semibold">Action plan</h2>
        {actionPlan.items.length === 0 ? (
          <p className="mt-2 text-sm text-neutral-500">No action items yet.</p>
        ) : (
          <>
            <p className="mb-4 text-xs text-neutral-500">
              Prioritized into a 90-day / 2-year / 5-year roadmap, with an
              estimated cost range per item.
            </p>
            <ol className="space-y-6">
              {URGENCY_TIERS.map((tier, index) => {
                const items = actionPlan.items.filter((item) => item.urgency === tier);
                if (items.length === 0) return null;
                return (
                  <li key={tier}>
                    <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-wide text-neutral-500 uppercase">
                      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-neutral-900 text-[10px] font-semibold text-white dark:bg-white dark:text-neutral-900">
                        {index + 1}
                      </span>
                      {URGENCY_LABELS[tier]}
                    </h3>
                    <ul className="space-y-2 border-l border-neutral-200 pl-5 dark:border-neutral-800">
                      {items.map((item) => (
                        <li
                          key={item.id}
                          className="rounded-md border border-neutral-200 px-3 py-2 text-xs dark:border-neutral-800"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-medium">
                              {SYSTEM_LABELS[item.system] ?? item.system}
                            </span>
                            <span className="ml-auto text-neutral-500">
                              {formatCostRange(item.cost_low, item.cost_high)}
                            </span>
                          </div>
                          <p className="mt-1.5 text-neutral-600 dark:text-neutral-400">
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
