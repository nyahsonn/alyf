import * as Sentry from "@sentry/nextjs";

// Next.js's own instrumentation hook (not Sentry-specific) -- called once
// per runtime the server starts. A blank NEXT_PUBLIC_SENTRY_DSN makes
// Sentry.init a safe no-op (confirmed: it still builds a client, just one
// whose transport has nothing to send to), so this needs no extra guard.
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    Sentry.init({
      dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
      environment: process.env.NODE_ENV,
      // Error monitoring only, not performance tracing -- matches the
      // backend's sentry_sdk.init (see backend/app/main.py).
      tracesSampleRate: 0,
    });
  }

  if (process.env.NEXT_RUNTIME === "edge") {
    Sentry.init({
      dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
      environment: process.env.NODE_ENV,
      tracesSampleRate: 0,
    });
  }
}

export const onRequestError = Sentry.captureRequestError;
