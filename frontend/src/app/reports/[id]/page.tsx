"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  api,
  ApiError,
  type ActionItem,
  type ActionPlan,
  type BuyerReport,
  type BuyerReportSystem,
  type Document,
  type EventStatus,
  type HomeReport,
} from "@/lib/api";
import {
  SYSTEM_LABELS,
  URGENCY_LABELS,
  URGENCY_TIERS,
  CONDITION_TONE,
  CONDITION_LABEL,
  EVENT_STATUS_LABEL,
  COST_DISCLAIMER,
  confidenceLabel,
  formatCostRange,
  isSafetyHazard,
  reportDisclaimer,
} from "@/lib/format";
import { Logo } from "@/components/Logo";

// Small, unobtrusive brand mark in the corner -- present on every state of
// this page (loading/error/pending/ready), not just the full report, since
// it's cheap to place once via absolute positioning rather than threading
// it through each state's own layout. Full icon+wordmark lockup, same as
// every other page, just sized down for a corner.
function CornerMark() {
  return (
    <div className="absolute top-6 right-6 sm:top-8 sm:right-8">
      <Logo height={36} />
    </div>
  );
}

// A system as either mode's payload shapes it -- BuyerReportSystem's fields
// plus HomeSystem's extra `finding_ids`, needed only in inspector mode to
// know which Finding row a given piece of text belongs to.
type ViewSystem = BuyerReportSystem & { finding_ids?: string[] };

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

// Deliberately the one pill in the system that breaks the muted palette --
// a solid fill instead of every other pill's soft tint -- reserved for
// wording that already names a genuine hazard (see isSafetyHazard).
function SafetyTag() {
  return (
    <span className="rounded-full bg-brick px-2.5 py-0.5 text-[11px] font-semibold tracking-wide text-surface uppercase">
      Safety concern
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const tone = status === "pending_review" ? "bg-ochre-soft text-ochre" : "bg-sage-soft text-sage";
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold tracking-wide uppercase ${tone}`}>
      {EVENT_STATUS_LABEL[status] ?? status}
    </span>
  );
}

// Cost lives in its own visually distinct block, separate from the finding
// and urgency it sits below -- background tint + badge, not another column
// in the same row -- with the disclaimer directly attached, not just once
// at the top or bottom of the page.
function CostBlock({ item }: { item: ActionItem }) {
  return (
    <div className="mt-3 rounded-xl border border-dashed border-line bg-surface-sunk px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-ochre-soft px-2 py-0.5 text-[10px] font-semibold tracking-wide text-ochre uppercase">
          AI cost estimate
        </span>
        <span className="font-mono text-sm font-semibold tabular-nums text-ink">
          {formatCostRange(item.cost_low, item.cost_high)}
        </span>
      </div>
      <p className="mt-1.5 text-[11px] leading-relaxed text-ink-faint">{COST_DISCLAIMER}</p>
    </div>
  );
}

// Click-to-edit text used for both a finding's wording and an action item's
// recommendation -- text-only, no add/delete, per the review workflow's
// scope.
function EditableText({
  value,
  onSave,
}: {
  value: string;
  onSave: (next: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);

  if (!editing) {
    return (
      <div className="flex items-start justify-between gap-3">
        <p className="text-[13.5px] leading-relaxed text-ink-soft">{value}</p>
        <button
          type="button"
          onClick={() => {
            setDraft(value);
            setEditing(true);
          }}
          className="shrink-0 text-[11px] font-medium text-ink-faint underline underline-offset-2 hover:text-ink"
        >
          Edit
        </button>
      </div>
    );
  }

  return (
    <div>
      <textarea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        rows={3}
        className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-[13.5px] text-ink focus:border-accent focus:outline-none"
      />
      <div className="mt-1.5 flex gap-3">
        <button
          type="button"
          disabled={saving}
          onClick={async () => {
            setSaving(true);
            await onSave(draft);
            setSaving(false);
            setEditing(false);
          }}
          className="text-[11px] font-medium text-accent underline underline-offset-2 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={() => setEditing(false)}
          className="text-[11px] font-medium text-ink-faint underline underline-offset-2"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function SystemsSection({
  systems,
  actionItems,
  editable,
  onSaveFinding,
}: {
  systems: ViewSystem[];
  actionItems: ActionItem[];
  editable: boolean;
  onSaveFinding?: (systemId: string, findingId: string, index: number, text: string) => Promise<void>;
}) {
  return (
    <section className="mb-12">
      <h2 className="mb-5 text-xs font-semibold tracking-wide text-ink-soft uppercase">Systems</h2>
      {systems.length === 0 ? (
        <p className="text-sm text-ink-soft">No systems found.</p>
      ) : (
        <ul className="space-y-3">
          {systems.map((system) => {
            const tone = CONDITION_TONE[system.condition] ?? CONDITION_TONE.not_mentioned;
            const label = CONDITION_LABEL[system.condition] ?? system.condition;
            const relatedActions = actionItems.filter((item) => item.system === system.name);
            const hazard = isSafetyHazard(
              ...system.findings,
              ...relatedActions.map((item) => item.recommendation),
            );
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
                    {label}
                  </span>
                  {hazard && <SafetyTag />}
                  <ConfidenceGauge value={system.condition_confidence} />
                  <span className="ml-auto font-mono text-xs tabular-nums text-ink-faint">
                    {system.estimated_age_years !== null
                      ? `${system.estimated_age_years} yrs old`
                      : "age unknown"}
                  </span>
                </div>
                {system.findings.length > 0 ? (
                  <ul className="mt-3 list-disc space-y-2 pl-4 text-[13.5px] leading-relaxed text-ink-soft">
                    {system.findings.map((finding, index) => {
                      const findingId = system.finding_ids?.[index];
                      return (
                        <li key={index}>
                          {editable && onSaveFinding && findingId ? (
                            <EditableText
                              value={finding}
                              onSave={(text) => onSaveFinding(system.id, findingId, index, text)}
                            />
                          ) : (
                            finding
                          )}
                        </li>
                      );
                    })}
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
  );
}

function ActionPlanSection({
  items,
  systems,
  editable,
  onSaveActionItem,
}: {
  items: ActionItem[];
  systems: ViewSystem[];
  editable: boolean;
  onSaveActionItem?: (
    itemId: string,
    input: { urgency?: string; recommendation?: string },
  ) => Promise<void>;
}) {
  return (
    <section>
      <h2 className="mb-1 text-xs font-semibold tracking-wide text-ink-soft uppercase">
        Action plan
      </h2>
      {items.length === 0 ? (
        <p className="mt-2 text-sm text-ink-soft">No action items yet.</p>
      ) : (
        <>
          <p className="mb-6 text-xs text-ink-faint">
            Prioritized into a 90-day / 2-year / 5-year roadmap. Findings and urgency reflect the
            inspector&apos;s review; the cost estimate on each item is a separate, AI-generated
            reference — see the note attached to it.
          </p>
          <ol className="space-y-8">
            {URGENCY_TIERS.map((tier, index) => {
              const tierItems = items.filter((item) => item.urgency === tier);
              if (tierItems.length === 0) return null;
              return (
                <li key={tier}>
                  <h3 className="mb-3 flex items-center gap-2.5 text-xs font-semibold tracking-wide text-ink-soft uppercase">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent font-mono text-[11px] font-semibold text-accent-ink">
                      {index + 1}
                    </span>
                    {URGENCY_LABELS[tier]}
                  </h3>
                  <ul className="space-y-3 border-l border-line pl-5">
                    {tierItems.map((item) => {
                      const system = systems.find((s) => s.name === item.system);
                      const hazard = isSafetyHazard(item.recommendation, ...(system?.findings ?? []));
                      return (
                        <li
                          key={item.id}
                          className="rounded-2xl border border-line bg-surface px-6 py-5 text-sm"
                        >
                          <div className="flex flex-wrap items-center gap-3">
                            <span className="font-medium text-ink">
                              {SYSTEM_LABELS[item.system] ?? item.system}
                            </span>
                            {hazard && <SafetyTag />}
                            {editable && onSaveActionItem && (
                              <select
                                value={item.urgency}
                                onChange={(event) =>
                                  onSaveActionItem(item.id, { urgency: event.target.value })
                                }
                                className="ml-auto rounded-full border border-line bg-surface px-2 py-1 text-[11px] font-medium text-ink-soft focus:border-accent focus:outline-none"
                              >
                                {URGENCY_TIERS.map((t) => (
                                  <option key={t} value={t}>
                                    {URGENCY_LABELS[t]}
                                  </option>
                                ))}
                              </select>
                            )}
                          </div>
                          {editable && onSaveActionItem ? (
                            <div className="mt-2">
                              <EditableText
                                value={item.recommendation}
                                onSave={(text) => onSaveActionItem(item.id, { recommendation: text })}
                              />
                            </div>
                          ) : (
                            <p className="mt-2 text-[13.5px] leading-relaxed text-ink-soft">
                              {item.recommendation}
                            </p>
                          )}
                          <CostBlock item={item} />
                        </li>
                      );
                    })}
                  </ul>
                </li>
              );
            })}
          </ol>
        </>
      )}
    </section>
  );
}

type Mode = "loading" | "inspector" | "buyer" | "error";

export default function ReportPage() {
  const params = useParams<{ id: string }>();
  const [mode, setMode] = useState<Mode>("loading");
  const [error, setError] = useState<string | null>(null);

  const [document, setDocument] = useState<Document | null>(null);
  const [inspectorName, setInspectorName] = useState<string | null>(null);
  const [homeReport, setHomeReport] = useState<HomeReport | null>(null);
  const [actionPlan, setActionPlan] = useState<ActionPlan | null>(null);
  const [eventStatus, setEventStatus] = useState<EventStatus | null>(null);

  const [buyerReport, setBuyerReport] = useState<BuyerReport | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadBuyerView() {
      try {
        const report = await api.getBuyerReport(params.id);
        if (cancelled) return;
        setBuyerReport(report);
        setMode("buyer");
      } catch (caught) {
        if (cancelled) return;
        setError(
          caught instanceof ApiError
            ? caught.message
            : "Something went wrong. Check the browser console.",
        );
        setMode("error");
      }
    }

    api
      .getDocument(params.id)
      .then(async (doc) => {
        const [me, home, plan, status] = await Promise.all([
          api.me(),
          api.getHomeReport(params.id),
          api.getActionPlan(params.id),
          api.getEventStatus(params.id),
        ]);
        if (cancelled) return;
        setDocument(doc);
        setInspectorName(me.name);
        setHomeReport(home);
        setActionPlan(plan);
        setEventStatus(status);
        setMode("inspector");
      })
      .catch(() => {
        // Not logged in as the owning inspector (or not logged in at all)
        // -- fall back to the public, buyer-facing view rather than an auth
        // error. A genuinely unreachable backend surfaces there too, since
        // getBuyerReport fails the same way getDocument just did.
        if (!cancelled) loadBuyerView();
      });

    return () => {
      cancelled = true;
    };
  }, [params.id]);

  const approve = useCallback(async () => {
    const status = await api.approveEvent(params.id);
    setEventStatus(status);
  }, [params.id]);

  const saveFinding = useCallback(
    async (systemId: string, findingId: string, index: number, text: string) => {
      await api.updateFinding(params.id, findingId, text);
      setHomeReport((prev) =>
        prev
          ? {
              ...prev,
              systems: prev.systems.map((system) =>
                system.id === systemId
                  ? {
                      ...system,
                      findings: system.findings.map((f, i) => (i === index ? text : f)),
                    }
                  : system,
              ),
            }
          : prev,
      );
    },
    [params.id],
  );

  const saveActionItem = useCallback(
    async (itemId: string, input: { urgency?: string; recommendation?: string }) => {
      const updated = await api.updateActionItem(params.id, itemId, input);
      setActionPlan((prev) =>
        prev
          ? { ...prev, items: prev.items.map((item) => (item.id === itemId ? updated : item)) }
          : prev,
      );
    },
    [params.id],
  );

  if (mode === "loading") {
    return (
      <main className="relative mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center px-6 py-10 text-center">
        <CornerMark />
        <p className="text-sm text-ink-soft">Loading your report…</p>
      </main>
    );
  }

  if (mode === "error") {
    return (
      <main className="relative mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center px-6 py-10 text-center">
        <CornerMark />
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

  if (mode === "buyer") {
    const report = buyerReport as BuyerReport;

    if (report.status === "pending_review") {
      return (
        <main className="relative mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center px-6 py-10 text-center">
          <CornerMark />
          <h1 className="font-display text-2xl font-medium tracking-tight">Almost ready</h1>
          <p className="mt-3 text-sm text-ink-soft">
            Your inspector is still reviewing this report. Check back soon — you&apos;ll see your
            full AI Home Health Report here once it&apos;s approved.
          </p>
        </main>
      );
    }

    return (
      <main className="relative mx-auto w-full max-w-3xl px-6 py-14">
        <CornerMark />
        <header className="mb-12">
          <h1 className="font-display text-3xl font-medium tracking-tight">
            AI Home Health Report
          </h1>
          {report.title && <p className="mt-2 text-sm text-ink-soft">{report.title}</p>}
          <p className="mt-4 text-xs text-ink-faint">{reportDisclaimer(report.inspector_name)}</p>
          <Link
            href={`/reports/${report.document_id}/timeline`}
            className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-3.5 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent hover:text-accent-ink"
          >
            View system timeline
            <span aria-hidden="true">→</span>
          </Link>
        </header>

        <SystemsSection systems={report.systems} actionItems={report.action_items} editable={false} />
        <ActionPlanSection items={report.action_items} systems={report.systems} editable={false} />
      </main>
    );
  }

  // inspector mode
  const doc = document as Document;
  const home = homeReport as HomeReport;
  const plan = actionPlan as ActionPlan;
  const status = eventStatus as EventStatus;

  return (
    <main className="relative mx-auto w-full max-w-3xl px-6 py-14">
      <CornerMark />
      <Link
        href="/upload"
        className="text-xs font-medium text-ink-faint underline underline-offset-2 hover:text-ink"
      >
        ← Upload another report
      </Link>

      <header className="mt-5 mb-12">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-display text-3xl font-medium tracking-tight">
            AI Home Health Report
          </h1>
          <StatusBadge status={status.status} />
        </div>
        <p className="mt-2 text-sm text-ink-soft">{doc.title}</p>
        <p className="mt-4 text-xs text-ink-faint">{reportDisclaimer(inspectorName)}</p>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <Link
            href={`/reports/${doc.id}/timeline`}
            className="inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-3.5 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent hover:text-accent-ink"
          >
            View system timeline
            <span aria-hidden="true">→</span>
          </Link>
          {status.status === "pending_review" && (
            <button
              type="button"
              onClick={approve}
              className="rounded-full bg-accent px-3.5 py-1.5 text-xs font-medium text-accent-ink transition-colors hover:opacity-90"
            >
              Approve for buyer
            </button>
          )}
        </div>
        <p className="mt-2 text-[11px] text-ink-faint">
          Review and correct the findings and roadmap below before approving — this is what your
          buyer will see.
          {status.status === "pending_review" &&
            " Left unreviewed, it auto-sends after a set window so delivery isn't blocked."}
        </p>
      </header>

      <SystemsSection
        systems={home.systems}
        actionItems={plan.items}
        editable
        onSaveFinding={saveFinding}
      />
      <ActionPlanSection
        items={plan.items}
        systems={home.systems}
        editable
        onSaveActionItem={saveActionItem}
      />
    </main>
  );
}
