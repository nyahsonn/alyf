import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// UX convenience only, not the security boundary -- the API's own 401s are
// (see backend/app/api/deps.py's CurrentInspectorDep). This just checks the
// session cookie's *presence*, not its signature/expiry, since verifying a
// JWT here would mean duplicating jwt_secret into the frontend process.
// An inspector-facing route with a stale/expired cookie still redirects
// correctly -- just one round trip later, once the page's own api.me() call
// gets a 401 back.
const SESSION_COOKIE = "alyf_session";

export function proxy(request: NextRequest) {
  if (request.cookies.get(SESSION_COOKIE)) {
    return NextResponse.next();
  }
  const loginUrl = new URL("/login", request.url);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  // Inspector-facing pages only -- /reports/* stays unauthenticated
  // (homeowner-facing, no login), same for /login, /signup, and the public
  // landing page at "/" itself. /dev is the old generic-pipeline test
  // harness, still gated the same way "/" used to be.
  matcher: ["/dev", "/upload"],
};
