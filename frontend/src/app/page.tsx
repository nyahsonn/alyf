"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";

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
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center px-6 py-14 text-center">
      <h1 className="font-display text-5xl font-medium tracking-tight italic">ALYF</h1>
      <p className="mt-6 max-w-lg text-base leading-relaxed text-ink-soft">
        ALYF turns your inspection report into an <strong className="text-ink">AI Home
        Health Report</strong> — a structured, prioritized breakdown of a home&apos;s
        systems, reviewed and approved by you, and handed to your buyer as a
        premium, white-labeled deliverable at the point of sale.
      </p>

      <div className="mt-9 flex flex-wrap items-center justify-center gap-4">
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
    </main>
  );
}
