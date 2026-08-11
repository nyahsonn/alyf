"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";

type Stage = "idle" | "uploading" | "home-report" | "action-plan" | "error";

const STAGE_COPY: Record<Exclude<Stage, "idle" | "error">, { label: string; progress: number }> = {
  uploading: { label: "Uploading PDF…", progress: 33 },
  "home-report": { label: "Reading your home's systems…", progress: 66 },
  "action-plan": { label: "Building your action plan…", progress: 100 },
};

export default function UploadPage() {
  const router = useRouter();
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [stage, setStage] = useState<Stage>("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [notifyEmail, setNotifyEmail] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .me()
      .then(() => setCheckingAuth(false))
      .catch(() => router.replace("/login"));
  }, [router]);

  const busy = stage !== "idle" && stage !== "error";

  const processFile = useCallback(
    async (file: File) => {
      if (file.type !== "application/pdf") {
        setError("Please upload a PDF file.");
        setStage("error");
        return;
      }

      setError(null);
      try {
        setStage("uploading");
        setProgress(STAGE_COPY.uploading.progress);
        const document = await api.uploadDocument(file, notifyEmail.trim() || undefined);

        setStage("home-report");
        setProgress(STAGE_COPY["home-report"].progress);
        await api.createHomeReport(document.id);

        setStage("action-plan");
        setProgress(STAGE_COPY["action-plan"].progress);
        await api.createActionPlan(document.id);

        router.push(`/reports/${document.id}`);
      } catch (caught) {
        setError(
          caught instanceof ApiError
            ? caught.message
            : "Something went wrong. Check the browser console.",
        );
        setStage("error");
      }
    },
    [router, notifyEmail],
  );

  const reset = () => {
    setStage("idle");
    setProgress(0);
    setError(null);
  };

  const stageCopy = stage !== "idle" && stage !== "error" ? STAGE_COPY[stage] : null;

  if (checkingAuth) {
    return (
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center px-6 py-14">
        <p className="text-sm text-ink-soft">One moment…</p>
      </main>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center px-6 py-14">
      <button
        type="button"
        onClick={() => api.logout().finally(() => router.push("/login"))}
        className="self-end text-xs font-medium text-ink-faint underline underline-offset-2 hover:text-ink"
      >
        Log out
      </button>

      <header className="mt-4 mb-10 text-center">
        <h1 className="font-display text-4xl font-medium tracking-tight italic">ALYF</h1>
        <p className="mt-2 text-sm text-ink-soft">
          Upload an inspection PDF to get your AI Home Health Report.
        </p>
      </header>

      {error && (
        <div
          role="alert"
          className="mb-6 rounded-2xl border border-brick/20 bg-brick-soft px-5 py-4 text-sm text-brick"
        >
          {error}
          <button
            type="button"
            onClick={reset}
            className="ml-3 font-medium underline underline-offset-2"
          >
            Try again
          </button>
        </div>
      )}

      <label className="mb-4 block text-left">
        <span className="text-xs font-medium text-ink-soft">
          Homeowner&apos;s email for weekly reminders (optional)
        </span>
        <input
          type="email"
          value={notifyEmail}
          onChange={(event) => setNotifyEmail(event.target.value)}
          disabled={busy}
          placeholder="homeowner@example.com"
          className="mt-1.5 w-full rounded-xl border border-line bg-surface px-3.5 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none disabled:opacity-50"
        />
      </label>

      <div
        onDragOver={(event) => {
          event.preventDefault();
          if (!busy) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          if (busy) return;
          const file = event.dataTransfer.files?.[0];
          if (file) processFile(file);
        }}
        onClick={() => {
          if (!busy) fileInput.current?.click();
        }}
        className={`flex min-h-64 flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
          busy ? "cursor-default border-line" : "cursor-pointer border-line-strong hover:border-accent"
        } ${isDragging ? "border-accent bg-accent-soft" : ""}`}
      >
        <input
          ref={fileInput}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) processFile(file);
          }}
        />

        {!busy ? (
          <>
            <p className="text-sm font-medium text-ink">Drag and drop your inspection PDF here</p>
            <p className="mt-1 text-xs text-ink-faint">or click to browse</p>
          </>
        ) : (
          <div className="w-full max-w-sm">
            <p className="text-sm font-medium text-ink">{stageCopy?.label}</p>
            <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-surface-sunk">
              <div
                className="h-full rounded-full bg-accent transition-all duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
