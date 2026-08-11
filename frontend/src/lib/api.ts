/**
 * Typed client for the ALYF FastAPI backend.
 *
 * The base URL comes from NEXT_PUBLIC_API_URL (see frontend/.env.local).
 * NEXT_PUBLIC_ variables are inlined at build time and visible in the browser,
 * so never put secrets in them.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export const API_PREFIX = "/api/v1";

/** Full-page navigation target for "Continue with Google" -- a real link,
 * not fetch(), since the provider's own login screen has to load. */
export const googleLoginUrl = `${API_BASE}${API_PREFIX}/auth/google/login`;

export type Document = {
  id: string;
  title: string;
  source_type: string;
  source_ref: string | null;
  status: string;
  notify_email: string | null;
  created_at: string;
};

export type Fact = {
  id: string;
  document_id: string;
  chunk_id: string | null;
  label: string;
  value: string;
  kind: string;
  confidence: number;
  created_at: string;
};

export type ExtractionResult = {
  document_id: string;
  facts_created: number;
  facts: Fact[];
};

export type HomeSystem = {
  id: string;
  document_id: string;
  name: string;
  estimated_age_years: number | null;
  estimated_age_confidence: number;
  condition: string;
  condition_confidence: number;
  findings: string[];
  /** Parallel to `findings` -- same order, same length. */
  finding_ids: string[];
  findings_confidence: number;
  created_at: string;
};

export type HomeReport = {
  document_id: string;
  systems: HomeSystem[];
};

export type ActionItem = {
  id: string;
  document_id: string;
  system: string;
  urgency: string;
  recommendation: string;
  cost_low: number;
  cost_high: number;
  cost_source: string;
  created_at: string;
};

export type ActionPlan = {
  document_id: string;
  items: ActionItem[];
};

/** A report's review status -- see backend InspectionEvent.status. */
export type EventStatus = {
  status: "pending_review" | "approved" | "auto_sent";
  reviewed_at: string | null;
};

export type Finding = {
  id: string;
  document_id: string;
  text: string;
};

export type BuyerReportSystem = {
  id: string;
  name: string;
  estimated_age_years: number | null;
  estimated_age_confidence: number;
  condition: string;
  condition_confidence: number;
  findings: string[];
  findings_confidence: number;
};

/** The public, unauthenticated view of a report -- what a buyer sees at its
 * link. Every field but `status`/`document_id` is absent while
 * status === "pending_review". */
export type BuyerReport = {
  status: "pending_review" | "approved" | "auto_sent";
  document_id: string;
  title: string | null;
  inspector_name: string | null;
  created_at: string | null;
  systems: BuyerReportSystem[];
  action_items: ActionItem[];
};

export type EvidenceItem = {
  fact_id: string;
  document_id: string;
  label: string;
  value: string;
  kind: string;
  score: number;
};

export type Answer = {
  question: string;
  answer: string;
  evidence: EvidenceItem[];
  insight_id: string | null;
};

export type Report = {
  id: string;
  document_id: string;
  title: string;
  summary: string;
  fact_count: number;
  created_at: string;
  body_markdown: string;
};

export type DbHealth = {
  status: string;
  database: string;
  pgvector: string;
  embedding_dimensions: number;
};

export type Inspector = {
  id: string;
  email: string;
  name: string | null;
  created_at: string;
};

/** Thrown for any non-2xx response, carrying the backend's detail message. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${API_PREFIX}${path}`, {
      ...init,
      headers: {
        ...(init?.body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
      // Required for the browser to send/receive the httpOnly session
      // cookie cross-port (frontend on :3000, backend on :8000 in dev --
      // different origins even though both are "localhost").
      credentials: "include",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      `Cannot reach the backend at ${API_BASE}. Is it running? (uvicorn app.main:app --reload)`,
      0,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const detail = payload?.detail;
    throw new ApiError(
      typeof detail === "string" ? detail : `Request failed (${response.status})`,
      response.status,
    );
  }

  return payload as T;
}

export const api = {
  health: () => request<DbHealth>("/health/db"),

  signup: (input: { email: string; password: string; name?: string }) =>
    request<Inspector>("/auth/signup", { method: "POST", body: JSON.stringify(input) }),

  login: (input: { email: string; password: string }) =>
    request<Inspector>("/auth/login", { method: "POST", body: JSON.stringify(input) }),

  logout: () => request<void>("/auth/logout", { method: "POST" }),

  me: () => request<Inspector>("/auth/me"),

  listDocuments: () => request<Document[]>("/documents"),

  createDocument: (input: { title: string; content: string }) =>
    request<Document>("/documents", {
      method: "POST",
      body: JSON.stringify({ ...input, source_type: "text" }),
    }),

  uploadDocument: (file: File, notifyEmail?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (notifyEmail) form.append("notify_email", notifyEmail);
    return request<Document>("/documents/upload", {
      method: "POST",
      body: form,
    });
  },

  deleteDocument: (documentId: string) =>
    request<void>(`/documents/${documentId}`, { method: "DELETE" }),

  unsubscribe: (documentId: string) =>
    request<void>(`/documents/${documentId}/notify-email`, { method: "DELETE" }),

  extract: (documentId: string) =>
    request<ExtractionResult>(`/documents/${documentId}/extract`, {
      method: "POST",
    }),

  listFacts: (documentId: string) =>
    request<Fact[]>(`/facts?document_id=${documentId}`),

  createHomeReport: (documentId: string) =>
    request<HomeReport>(`/documents/${documentId}/home-report`, {
      method: "POST",
    }),

  getHomeReport: (documentId: string) =>
    request<HomeReport>(`/documents/${documentId}/home-report`),

  createActionPlan: (documentId: string) =>
    request<ActionPlan>(`/documents/${documentId}/action-plan`, {
      method: "POST",
    }),

  getActionPlan: (documentId: string) =>
    request<ActionPlan>(`/documents/${documentId}/action-plan`),

  getEventStatus: (documentId: string) =>
    request<EventStatus>(`/documents/${documentId}/status`),

  approveEvent: (documentId: string) =>
    request<EventStatus>(`/documents/${documentId}/approve`, { method: "POST" }),

  updateFinding: (documentId: string, findingId: string, text: string) =>
    request<Finding>(`/documents/${documentId}/findings/${findingId}`, {
      method: "PATCH",
      body: JSON.stringify({ text }),
    }),

  updateActionItem: (
    documentId: string,
    itemId: string,
    input: { urgency?: string; recommendation?: string },
  ) =>
    request<ActionItem>(`/documents/${documentId}/action-items/${itemId}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),

  getBuyerReport: (documentId: string) =>
    request<BuyerReport>(`/documents/${documentId}/buyer-report`),

  ask: (input: { question: string; document_id?: string; top_k?: number }) =>
    request<Answer>("/ask", { method: "POST", body: JSON.stringify(input) }),

  createReport: (documentId: string) =>
    request<Report>("/reports", {
      method: "POST",
      body: JSON.stringify({ document_id: documentId }),
    }),

  getDocument: (documentId: string) => request<Document>(`/documents/${documentId}`),
};
