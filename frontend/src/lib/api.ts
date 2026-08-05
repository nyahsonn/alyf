/**
 * Typed client for the ALYF FastAPI backend.
 *
 * The base URL comes from NEXT_PUBLIC_API_URL (see frontend/.env.local).
 * NEXT_PUBLIC_ variables are inlined at build time and visible in the browser,
 * so never put secrets in them.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export const API_PREFIX = "/api/v1";

export type Document = {
  id: string;
  title: string;
  source_type: string;
  source_ref: string | null;
  status: string;
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

  listDocuments: () => request<Document[]>("/documents"),

  createDocument: (input: { title: string; content: string }) =>
    request<Document>("/documents", {
      method: "POST",
      body: JSON.stringify({ ...input, source_type: "text" }),
    }),

  uploadDocument: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Document>("/documents/upload", {
      method: "POST",
      body: form,
    });
  },

  deleteDocument: (documentId: string) =>
    request<void>(`/documents/${documentId}`, { method: "DELETE" }),

  extract: (documentId: string) =>
    request<ExtractionResult>(`/documents/${documentId}/extract`, {
      method: "POST",
    }),

  listFacts: (documentId: string) =>
    request<Fact[]>(`/facts?document_id=${documentId}`),

  ask: (input: { question: string; document_id?: string; top_k?: number }) =>
    request<Answer>("/ask", { method: "POST", body: JSON.stringify(input) }),

  createReport: (documentId: string) =>
    request<Report>("/reports", {
      method: "POST",
      body: JSON.stringify({ document_id: documentId }),
    }),
};
