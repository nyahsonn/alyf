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
  isSafetyHazard,
} from "@/lib/format";

function nextRecommendedAction(system: HomeSystem, items: ActionItem[]): ActionItem | null {
  const matches = items.filter((item) => item.system === system.name);
  if (matches.length === 0) return null;
  return [...matches].sort(
    (a, b) => URGENCY_TIERS.indexOf(a.urgency as never) - URGENCY_TIERS.indexOf(b.urgency as never),
  )[0];
}

// Deliberately the one pill that breaks the muted palette -- a solid fill
// instead of every other pill's soft tint -- reserved for wording that
// already names a genuine hazard (see isSafetyHazard).
function SafetyTag() {
  return (
    <span className="rounded-full bg-brick px-2.5 py-0.5 text-[11px] font-semibold tracking-wide text-surface uppercase">
      Safety concern
    </span>
  );
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
        <p className="text-sm text-brick">{error}</p>
        <Link href="/upload" className="mt-4 text-sm font-medium text-accent underline underline-offset-2">
          Upload another report
        </Link>
      </main>
    );
  }

  if (!document || !homeReport || !actionPlan) {
    return (
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center px-6 py-10 text-center">
        <p className="text-sm text-ink-soft">Loading your timeline…</p>
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
    <main className="mx-auto w-full max-w-3xl px-6 py-14">
      <Link
        href={`/reports/${document.id}`}
        className="text-xs font-medium text-ink-faint underline underline-offset-2 hover:text-ink"
      >
        ← Back to report
      </Link>

      <header className="mt-5 mb-12">
        <h1 className="font-display text-3xl font-medium tracking-tight">System timeline</h1>
        <p className="mt-2 text-sm text-ink-soft">{document.title}</p>
        <p className="mt-4 text-xs text-ink-faint">
          Install years and remaining life below are calculated, not measured: install year is
          back-dated from the report&apos;s estimated system age, and lifespan uses typical
          industry ranges for that type of system — not an assessment of this specific unit.
        </p>
      </header>

      {entries.length === 0 ? (
        <p className="text-sm text-ink-soft">No systems found.</p>
      ) : (
        <ol className="space-y-8 border-l border-line pl-6">
          {entries.map(({ system, installYear, action }) => {
            const lifespan = TYPICAL_LIFESPAN_YEARS[system.name];
            const remaining =
              lifespan && system.estimated_age_years !== null
                ? [lifespan[0] - system.estimated_age_years, lifespan[1] - system.estimated_age_years]
                : null;

            return (
              <li key={system.id} className="relative">
                <span className="absolute top-1.5 -left-[29px] h-3 w-3 rounded-full border-2 border-paper bg-accent" />
                <div className="rounded-2xl border border-line bg-surface px-6 py-5 text-sm">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="font-medium text-ink">
                      {SYSTEM_LABELS[system.name] ?? system.name}
                    </span>
                    <span className="font-mono text-xs tabular-nums text-ink-faint">
                      {installYear !== null
                        ? `installed ~${installYear} (${system.estimated_age_years} yrs old)`
                        : "install year unknown"}
                    </span>
                  </div>

                  <p className="mt-3 text-[13.5px] leading-relaxed text-ink-soft">
                    Typical lifespan for this system type:{" "}
                    <span className="font-mono tabular-nums">
                      {lifespan ? `${lifespan[0]}–${lifespan[1]} yrs` : "no reference range available"}
                    </span>
                    {remaining &&
                      (remaining[1] > 0
                        ? ` — roughly ${Math.max(remaining[0], 0)}–${remaining[1]} yrs of typical life left (estimate)`
                        : " — already past the typical range for this system type (estimate)")}
                  </p>

                  <div className="mt-4 border-t border-dashed border-line pt-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[11px] font-semibold tracking-wide text-ink-faint uppercase">
                        Next action
                      </span>
                      {action && (
                        <>
                          <span className="rounded-full bg-accent-soft px-2.5 py-0.5 text-[11px] font-semibold text-accent">
                            {URGENCY_LABELS[action.urgency] ?? action.urgency}
                          </span>
                          {isSafetyHazard(action.recommendation, ...system.findings) && <SafetyTag />}
                          <span className="ml-auto font-mono text-xs font-semibold tabular-nums text-accent">
                            {formatCostRange(action.cost_low, action.cost_high)}
                          </span>
                        </>
                      )}
                    </div>
                    <p className={`mt-2 text-[13.5px] leading-relaxed ${action ? "text-ink" : "text-ink-faint"}`}>
                      {action ? action.recommendation : "None at this time."}
                    </p>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </main>
  );
}
