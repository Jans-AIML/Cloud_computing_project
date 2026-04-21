/**
 * API client — all calls go through API Gateway.
 * The base URL is set via the VITE_API_URL environment variable.
 * In development, Vite proxies /api → localhost:8000.
 */

const BASE_URL = import.meta.env.VITE_API_URL ?? '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${BASE_URL}${path}`
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(error.detail ?? 'Request failed')
  }
  return res.json() as Promise<T>
}

// ── Types ──────────────────────────────────────────────────────────────────────

export interface DocumentSummary {
  id: string
  source_type: string
  title: string | null
  source_url: string | null
  text_snippet: string | null
  word_count: number | null
  ingested_at: string
  evidence_card_count: number
}

export interface UploadRequest {
  filename: string
  content_type: string
  source_type: 'pdf' | 'email' | 'url'
  source_url?: string
  consent_given: boolean
}

export interface UploadResponse {
  document_id: string
  upload_url: string
  expires_in_seconds: number
}

export interface SearchResult {
  chunk_id: string
  document_id: string
  chunk_text: string
  score: number
  citation_label: string | null
  citation_url: string | null
  topic_tags: string[]
  source_type: string | null
}

export interface Citation {
  label: string
  url: string | null
  excerpt: string
  source_type?: string | null
}

export interface RagResponse {
  answer: string
  citations: Citation[]
  input_tokens: number
  output_tokens: number
  latency_ms: number
}

export interface BriefTemplate {
  id: string
  name: string
  description: string
  typical_length: string
}

export interface BriefRequest {
  template_id: string
  goal: string
  audience: string
  tone: 'formal' | 'community'
  extra_context: string
}

export interface BriefResponse {
  draft: string
  footnotes: Citation[]
  template_id: string
  input_tokens: number
  output_tokens: number
}

// ── API calls ──────────────────────────────────────────────────────────────────

export const api = {
  // Documents
  listDocuments: (limit = 20, offset = 0) =>
    request<DocumentSummary[]>(`/documents?limit=${limit}&offset=${offset}`),

  requestUpload: (payload: UploadRequest) =>
    request<UploadResponse>('/documents/upload', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  uploadFileToS3: async (uploadUrl: string, file: File): Promise<void> => {
    const res = await fetch(uploadUrl, {
      method: 'PUT',
      body: file,
      headers: { 'Content-Type': file.type },
    })
    if (!res.ok) throw new Error('File upload to S3 failed')
  },

  deleteDocument: (id: string) =>
    request<void>(`/documents/${id}`, { method: 'DELETE' }),

  processDocument: (id: string) =>
    request<{ document_id: string; status: string }>(`/documents/${id}/process`, { method: 'POST' }),

  // Search
  search: (q: string, topK = 8, topics: string[] = []) => {
    const params = new URLSearchParams({ q, top_k: String(topK) })
    topics.forEach((t) => params.append('topic', t))
    return request<SearchResult[]>(`/search?${params}`)
  },

  // RAG
  ragQuery: (question: string, topK = 6) =>
    request<RagResponse>('/rag/query', {
      method: 'POST',
      body: JSON.stringify({ question, top_k: topK }),
    }),

  // Streaming RAG — returns a ReadableStream
  ragStream: (question: string, topK = 6): EventSource => {
    // NOTE: EventSource only supports GET; for streaming POST we use fetch + ReadableStream
    // This endpoint uses SSE via fetch
    return new EventSource(
      `${BASE_URL}/rag/stream?question=${encodeURIComponent(question)}&top_k=${topK}`
    )
  },

  // Briefs
  listTemplates: () => request<BriefTemplate[]>('/briefs/templates'),

  generateBrief: (payload: BriefRequest) =>
    request<BriefResponse>('/briefs/generate', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
