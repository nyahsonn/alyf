"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  api,
  ApiError,
  type ActionItem,
  type ActionPlan,
  type Document,
  type HomeReport,
  type HomeSystem,
} from "@/lib/api";
import {
  SYSTEM_LABELS,
  URGENCY_LABELS,
  URGENCY_TIERS,
  TYPICAL_LIFESPAN_YEARS,
  formatCostRange,
} from "@/lib/format";

function nextRecommendedAction(system: HomeSystem, items: ActionItem[]): ActionItem | null {
  const matches = items.filter((item) => item.system === system.name);
  if (matches.length === 0) return null;
  return [...matches].sort(
    (a, b) => URGENCY_TIERS.indexOf(a.urgency as never) - URGENCY_TIERS.indexOf(b.urgency as never),
  )[0];
}

export default function TimelinePage() {
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
        <Link href="/upload" className="mt-4 text-sm font-medium underline underline-offset-2">
          Upload another report
        </Link>
      </main>
    );
  }

  if (!document || !homeReport || !actionPlan) {
    return (
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center px-6 py-10 text-center">
        <p className="text-sm text-neutral-500 dark:text-neutral-400">Loading your timeline…</p>
      </main>
    );
  }

  // The report never states an inspection date today, so the document's
  // upload date is the closest thing to "now" for backing out an install
  // year from the AI's estimated system age.
  const asOfYear = new Date(document.created_at).getFullYear();

  const entries = homeReport.systems
    .map((system) => ({
      system,
      installYear:
        system.estimated_age_years !== null ? asOfYear - system.estimated_age_years : null,
      action: nextRecommendedAction(system, actionPlan.items),
    }))
    // Oldest install first, so the page reads as a timeline. Systems with an
    // unknown age can't be placed on it, so they fall to the end.
    .sort((a, b) => {
      if (a.installYear === null && b.installYear === null) return 0;
      if (a.installYear === null) return 1;
      if (b.installYear === null) return -1;
      return a.installYear - b.installYear;
    });

  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-10">
      <Link
        href={`/reports/${document.id}`}
        className="text-xs font-medium text-neutral-500 underline underline-offset-2 hover:text-neutral-700 dark:hover:text-neutral-300"
      >
        ← Back to report
      </Link>

      <header className="mt-4 mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">System timeline</h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">{document.title}</p>
        <p className="mt-3 text-xs text-neutral-500 dark:text-neutral-400">
          Install years and remaining life below are calculated, not measured: install year is
          back-dated from the report&apos;s estimated system age, and lifespan uses typical
          industry ranges for that type of system — not an assessment of this specific unit.
        </p>
      </header>

      {entries.length === 0 ? (
        <p className="text-sm text-neutral-500">No systems found.</p>
      ) : (
        <ol className="space-y-6 border-l border-neutral-200 pl-5 dark:border-neutral-800">
          {entries.map(({ system, installYear, action }) => {
            const lifespan = TYPICAL_LIFESPAN_YEARS[system.name];
            const remaining =
              lifespan && system.estimated_age_years !== null
                ? [lifespan[0] - system.estimated_age_years, lifespan[1] - system.estimated_age_years]
                : null;

            return (
              <li key={system.id} className="relative">
                <span className="absolute top-1 -left-[26px] h-2.5 w-2.5 rounded-full bg-neutral-900 dark:bg-white" />
                <div className="rounded-md border border-neutral-200 px-3 py-2 text-xs dark:border-neutral-800">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{SYSTEM_LABELS[system.name] ?? system.name}</span>
                    <span className="text-neutral-500">
                      {installYear !== null
                        ? `installed ~${installYear} (${system.estimated_age_years} yrs old)`
                        : "install year unknown"}
                    </span>
                  </div>

                  <p className="mt-1.5 text-neutral-600 dark:text-neutral-400">
                    Typical lifespan for this system type:{" "}
                    {lifespan ? `${lifespan[0]}–${lifespan[1]} yrs` : "no reference range available"}
                    {remaining &&
                      (remaining[1] > 0
                        ? ` — roughly ${Math.max(remaining[0], 0)}–${remaining[1]} yrs of typical life left (estimate)`
                        : " — already past the typical range for this system type (estimate)")}
                  </p>

                  <p className="mt-1.5 text-neutral-600 dark:text-neutral-400">
                    <span className="font-medium text-neutral-700 dark:text-neutral-300">
                      Next recommended action:
                    </span>{" "}
                    {action ? (
                      <>
                        {action.recommendation}{" "}
                        <span className="text-neutral-400">
                          ({URGENCY_LABELS[action.urgency] ?? action.urgency},{" "}
                          {formatCostRange(action.cost_low, action.cost_high)})
                        </span>
                      </>
                    ) : (
                      "none at this time"
                    )}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </main>
  );
}
