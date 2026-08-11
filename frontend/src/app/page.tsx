"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { Logo } from "@/components/Logo";

export default function LandingPage() {
  const router = useRouter();
  const [checkingAuth, setCheckingAuth] = useState(true);

  useEffect(() => {
    api
      .me()
      // Already signed in -- send a returning inspector straight to their
      // dashboard rather than showing them marketing copy.
      .then(() => router.replace("/upload"))
      .catch(() => setCheckingAuth(false));
  }, [router]);

  if (checkingAuth) {
    return <main className="flex flex-1" />;
  }

  return (
    <main className="relative flex-1 overflow-hidden">
      {/* Decorative depth only -- same accent/sage tokens as the rest of the
          product, not new colors, so this still reads as ALYF rather than a
          bolted-on marketing page. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-40 -right-40 h-[32rem] w-[32rem] rounded-full bg-accent-soft blur-3xl"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 -left-32 h-96 w-96 rounded-full bg-sage-soft blur-3xl"
      />

      <div className="relative mx-auto w-full max-w-5xl px-6 py-16 sm:py-20">
        <Logo height={28} />

        <div className="mt-10 grid items-center gap-14 lg:mt-16 lg:grid-cols-[1.1fr_1fr] lg:gap-10">
          <div>
            <p className="text-xs font-semibold tracking-wide text-accent uppercase">
              For home inspectors
            </p>
            <h1 className="mt-3 font-display text-4xl leading-[1.1] font-medium tracking-tight sm:text-5xl">
              Turn every inspection into an{" "}
              <span className="italic text-accent">AI Home Health Report</span>
            </h1>
            <p className="mt-5 max-w-md text-base leading-relaxed text-ink-soft">
              ALYF reads your inspection PDF and builds a structured, prioritized
              report — findings and urgency you review and approve, cost estimates
              kept clearly separate — then hands your buyer a premium, white-labeled
              deliverable at closing.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-5">
              <Link
                href="/signup"
                className="rounded-xl bg-accent px-6 py-2.5 text-sm font-medium text-accent-ink transition-colors hover:bg-accent/90"
              >
                Sign up
              </Link>
              <Link
                href="/login"
                className="text-sm font-medium text-accent underline underline-offset-2"
              >
                Log in
              </Link>
            </div>
          </div>

          <ReportPreviewCard />
        </div>

        <ul className="mt-20 grid gap-4 sm:grid-cols-3 lg:mt-28">
          <FeatureCard
            title="AI-extracted findings"
            body="Every system's age, condition, and findings pulled straight from the source PDF, with a confidence score per field."
          />
          <FeatureCard
            title="Review, then approve"
            body="Nothing reaches a buyer un-reviewed. You edit and sign off on findings and urgency before the report unlocks."
          />
          <FeatureCard
            title="Costs, clearly separate"
            body="AI-estimated cost ranges sit apart from your professional findings — badged, disclaimed, never mistaken for your call."
          />
        </ul>
      </div>
    </main>
  );
}

function FeatureCard({ title, body }: { title: string; body: string }) {
  return (
    <li className="rounded-2xl border border-line bg-surface px-5 py-5">
      <p className="text-sm font-medium text-ink">{title}</p>
      <p className="mt-1.5 text-[13px] leading-relaxed text-ink-soft">{body}</p>
    </li>
  );
}

// A faithful, miniature echo of the real report page -- the same condition
// pill / cost-block treatment used in frontend/src/app/reports/[id]/page.tsx
// -- so a visitor's first impression is the actual product, not a generic
// illustration.
function ReportPreviewCard() {
  return (
    <div className="relative rounded-2xl border border-line bg-surface p-6 shadow-[0_1px_2px_rgba(18,25,29,0.04),0_12px_32px_-16px_rgba(18,25,29,0.18)]">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold tracking-wide text-ink-soft uppercase">
          AI Home Health Report
        </p>
        <span className="rounded-full bg-sage-soft px-2.5 py-0.5 text-[10px] font-semibold tracking-wide text-sage uppercase">
          Approved
        </span>
      </div>

      <div className="mt-5 border-t border-dashed border-line pt-5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-ink">HVAC</span>
          <span className="rounded-full bg-brick-soft px-2.5 py-0.5 text-[11px] font-semibold tracking-wide text-brick uppercase">
            Repair or Replace
          </span>
        </div>
        <p className="mt-2.5 text-[13px] leading-relaxed text-ink-soft">
          Furnace flue appears single-wall; double-wall piping is typically
          recommended for this unit.
        </p>

        <div className="mt-3.5 rounded-xl border border-dashed border-line bg-surface-sunk px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-ochre-soft px-2 py-0.5 text-[10px] font-semibold tracking-wide text-ochre uppercase">
              AI cost estimate
            </span>
            <span className="font-mono text-sm font-semibold tabular-nums text-ink">
              $700 – $1,800
            </span>
          </div>
          <p className="mt-1.5 text-[10.5px] leading-relaxed text-ink-faint">
            Not part of the inspector&apos;s findings — confirm scope and cost with a
            licensed contractor.
          </p>
        </div>
      </div>
    </div>
  );
}
