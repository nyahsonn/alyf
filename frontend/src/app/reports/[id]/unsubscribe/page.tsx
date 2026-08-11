"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";

type Status = "working" | "done" | "error";

export default function UnsubscribePage() {
  const params = useParams<{ id: string }>();
  const [status, setStatus] = useState<Status>("working");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .unsubscribe(params.id)
      .then(() => setStatus("done"))
      .catch((caught) => {
        setError(
          caught instanceof ApiError
            ? caught.message
            : "Something went wrong. Check the browser console.",
        );
        setStatus("error");
      });
  }, [params.id]);

  return (
    <main className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center px-6 py-10 text-center">
      {status === "working" && <p className="text-sm text-ink-soft">One moment…</p>}

      {status === "done" && (
        <>
          <p className="text-sm text-ink">
            You won&apos;t receive any more roadmap reminders for this report.
          </p>
          <Link
            href={`/reports/${params.id}`}
            className="mt-4 text-sm font-medium text-accent underline underline-offset-2"
          >
            View the report
          </Link>
        </>
      )}

      {status === "error" && (
        <>
          <p className="text-sm text-brick">{error}</p>
          <Link
            href={`/reports/${params.id}`}
            className="mt-4 text-sm font-medium text-accent underline underline-offset-2"
          >
            View the report
          </Link>
        </>
      )}
    </main>
  );
}
