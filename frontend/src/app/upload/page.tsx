"use client";

import { useCallback, useRef, useState } from "react";
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
  const [stage, setStage] = useState<Stage>("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

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
        const document = await api.uploadDocument(file);

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
    [router],
  );

  const reset = () => {
    setStage("idle");
    setProgress(0);
    setError(null);
  };

  const stageCopy = stage !== "idle" && stage !== "error" ? STAGE_COPY[stage] : null;

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center px-6 py-10">
      <header className="mb-8 text-center">
        <h1 className="text-3xl font-semibold tracking-tight">ALYF</h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
          Upload an inspection PDF to get your AI Home Health Report.
        </p>
      </header>

      {error && (
        <div
          role="alert"
          className="mb-6 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200"
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
        className={`flex min-h-64 flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
          busy
            ? "cursor-default border-neutral-200 dark:border-neutral-800"
            : "cursor-pointer border-neutral-300 hover:border-neutral-400 dark:border-neutral-700 dark:hover:border-neutral-500"
        } ${isDragging ? "border-neutral-900 bg-neutral-50 dark:border-white dark:bg-neutral-900" : ""}`}
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
            <p className="text-sm font-medium">Drag and drop your inspection PDF here</p>
            <p className="mt-1 text-xs text-neutral-500">or click to browse</p>
          </>
        ) : (
          <div className="w-full max-w-sm">
            <p className="text-sm font-medium">{stageCopy?.label}</p>
            <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800">
              <div
                className="h-full rounded-full bg-neutral-900 transition-all duration-500 dark:bg-white"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
