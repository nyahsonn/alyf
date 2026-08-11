import * as Sentry from "@sentry/nextjs";

// Browser-side init -- Next.js loads this file automatically (the
// "instrumentation-client" filename is a Next.js convention, not just a
// Sentry one). Same blank-DSN-is-a-safe-no-op behavior as instrumentation.ts.
Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NODE_ENV,
  tracesSampleRate: 0,
});

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
