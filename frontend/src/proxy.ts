import { NextResponse } from "next/server";

// Previously did a UX-shortcut redirect here by checking for the
// alyf_session cookie's presence on the incoming request (never its
// signature/expiry -- verifying a JWT here would mean duplicating
// jwt_secret into the frontend process). That only ever worked by
// accident: in local dev, the frontend (localhost:3000) and backend
// (localhost:8000) share the hostname "localhost", and cookies are scoped
// by hostname only, not port, so the backend-set cookie was visible here
// too. In any real deployment the frontend and backend sit on genuinely
// different domains (e.g. vercel.app / up.railway.app) -- the cookie is
// only ever sent to the backend, this middleware never sees it, and every
// visit to an inspector-facing route redirected to /login regardless of
// actual login state, Google sign-in included.
//
// The real check already lives where it has to: each inspector-facing
// page calls GET /auth/me itself (a real credentialed cross-origin fetch)
// and redirects to /login on a 401 -- see frontend/src/app/upload/page.tsx
// and frontend/src/app/dev/page.tsx.
export function proxy() {
  return NextResponse.next();
}
