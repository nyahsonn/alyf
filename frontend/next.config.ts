import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  /* config options here */
};

export default withSentryConfig(nextConfig, {
  // No org/project/authToken set -- source maps are never uploaded, so
  // captured errors show minified stack traces rather than readable ones.
  // Errors are still captured either way; add those three once you want
  // symbolicated traces (see README, "Error monitoring").
  silent: true,
});
