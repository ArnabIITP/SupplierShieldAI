import { createClient } from '@supabase/supabase-js'
import type {
  Analytics, Assessment, AuditEvent, Dashboard, Decision,
  Supplier, VerificationItem, VerificationResult,
} from './types'

const base = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

export const supabase = supabaseUrl && supabaseAnonKey
  ? createClient(supabaseUrl, supabaseAnonKey)
  : null

async function request<T>(path: string, init?: RequestInit, external = false): Promise<T> {
  const session = (await supabase?.auth.getSession())?.data.session
  const workspaceId = typeof localStorage === 'undefined'
    ? null
    : localStorage.getItem('supplierShield.workspaceId')
  const headers = new Headers(init?.headers)
  if (!(init?.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (session?.access_token) headers.set('Authorization', `Bearer ${session.access_token}`)
  if (workspaceId) headers.set('X-Workspace-ID', workspaceId)
  const url = external ? path : `${base}/api/v1${path}`
  const res = await fetch(url, { ...init, headers })
  if (!res.ok) {
    const err = await res.json().catch(() => null)
    throw new Error(err?.detail || `Request failed (${res.status})`)
  }
  return res.json()
}

export const api = {
  // ── Identity (PRD Sec15.1) ───────────────────────────────────────────────
  me: () => request<{ user_id: string; workspaces: { id: string; name: string; role: string }[] }>('/me'),

  // ── Onboarding (PRD Sec15.1) ──────────────────────────────────────────────
  onboardingComplete: (name: string) =>
    request<{ id: string; name: string; role: string }>('/onboarding/complete', {
      method: 'POST', body: JSON.stringify({ name }),
    }),

  // ── Workspaces ─────────────────────────────────────────────────────────
  workspaces: () => request<{ id: string; name: string; role: string }[]>('/workspaces'),
  inviteWorkspaceMember: (email: string, role: string) =>
    request<{ status: string; email: string; role: string }>('/workspaces/invite', {
      method: 'POST',
      body: JSON.stringify({ email, role }),
    }),

  // ── Dashboard ──────────────────────────────────────────────────────────
  dashboard: () => request<Dashboard>('/dashboard'),

  // ── Suppliers (PRD Sec15.2) ──────────────────────────────────────────────
  suppliers: (q = '', category = '', status = '') => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (category) params.set('category', category)
    if (status) params.set('status', status)
    const qs = params.toString()
    return request<Supplier[]>(`/suppliers${qs ? `?${qs}` : ''}`)
  },
  getSupplier: (id: string) => request<Supplier>(`/suppliers/${id}`),
  createSupplier: (body: object) =>
    request<Supplier>('/suppliers', { method: 'POST', body: JSON.stringify(body) }),
  patchSupplier: (id: string, body: object) =>
    request<Supplier>(`/suppliers/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  supplierAssessments: (id: string) =>
    request<Assessment[]>(`/suppliers/${id}/assessments`),
  supplierTransactions: (id: string) =>
    request<{ id: string; amount: number; currency: string; status: string; created_at: string }[]>(
      `/suppliers/${id}/transactions`
    ),

  // ── Transactions (PRD Sec15.3) ───────────────────────────────────────────
  createTransaction: (supplierId: string, body: object) =>
    request<{ id: string; supplier_id: string; amount: number; status: string }>(
      `/suppliers/${supplierId}/transactions`, { method: 'POST', body: JSON.stringify(body) }
    ),
  getTransaction: (id: string) =>
    request<{ id: string; supplier_id: string; amount: number; currency: string; status: string; created_at: string }>(
      `/transactions/${id}`
    ),
  assessTransaction: (transactionId: string) =>
    request<Assessment>(`/transactions/${transactionId}/assessments`, { method: 'POST' }),

  // ── Assessments (PRD Sec15.4) ────────────────────────────────────────────
  assessments: (riskCategory = '') => {
    const params = new URLSearchParams()
    if (riskCategory) params.set('risk_category', riskCategory)
    const qs = params.toString()
    return request<Assessment[]>(`/assessments${qs ? `?${qs}` : ''}`)
  },
  getAssessment: (id: string) => request<Assessment>(`/assessments/${id}`),
  /** Legacy direct-create: supplier_id + transaction params in one call */
  createAssessment: (body: object) =>
    request<Assessment>('/assessments', { method: 'POST', body: JSON.stringify(body) }),

  // ── AI Analysis ─────────────────────────────────────────────────────────
  getAiAnalysis: (id: string) =>
    request<{ assessment_id: string; status: string; analysis: Assessment['ai_analysis'] }>(
      `/assessments/${id}/ai-analysis`
    ),
  refreshAiAnalysis: (id: string) =>
    request<{ assessment_id: string; status: string; analysis: Assessment['ai_analysis'] }>(
      `/assessments/${id}/ai-analysis`, { method: 'POST' }
    ),

  // ── Verification (PRD Sec15.5) ──────────────────────────────────────────
  startVerification: (assessmentId: string) =>
    request<VerificationResult>(`/assessments/${assessmentId}/verification`, { method: 'POST' }),
  getVerificationByAssessment: (assessmentId: string) =>
    request<VerificationResult>(`/assessments/${assessmentId}/verification`),
  getVerificationCase: (caseId: string) =>
    request<VerificationResult & { priority: string }>(`/verification/${caseId}`),
  updateVerificationItem: (caseId: string, itemId: string, status: VerificationItem['status'], reviewerNote?: string) =>
    request<VerificationItem>(`/verification/${caseId}/items/${itemId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status, reviewer_note: reviewerNote }),
    }),
  verificationDecision: (caseId: string, action: string, reason: string) =>
    request<Decision>(`/verification/${caseId}/decision`, {
      method: 'POST', body: JSON.stringify({ action, reason }),
    }),

  // Legacy: item update by ID only (backwards compat)
  updateVerification: (itemId: string, status: VerificationItem['status'], reviewerNote?: string) =>
    request<VerificationItem>(`/verification-items/${itemId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status, reviewer_note: reviewerNote }),
    }),

  // ── Decisions ─────────────────────────────────────────────────────────
  decide: (id: string, action: string, reason: string) =>
    request<Decision>(`/assessments/${id}/decisions`, {
      method: 'POST', body: JSON.stringify({ action, reason }),
    }),
  getDecisions: (id: string) => request<Decision[]>(`/assessments/${id}/decisions`),
  supplierDocuments: (id: string) => request<any[]>(`/suppliers/${id}/documents`),
  deleteSupplier: (id: string) => request<{ status: string }>(`/suppliers/${id}`, { method: 'DELETE' }),
  deleteDocument: (id: string) => request<{ status: string }>(`/documents/${id}`, { method: 'DELETE' }),
  deleteAssessment: (id: string) => request<{ status: string }>(`/assessments/${id}`, { method: 'DELETE' }),

  // ── Razorpay test order (D8) ─────────────────────────────────────────────
  razorpayTestOrder: (assessmentId: string) =>
    request<{ order_id: string; amount: number; currency: string; status: string }>(
      `/assessments/${assessmentId}/razorpay-test-order`, { method: 'POST' }
    ),

  // ── Documents ─────────────────────────────────────────────────────────
  uploadDocument: (file: File, documentType: string, supplierId?: string, transactionId?: string) => {
    const data = new FormData()
    data.append('file', file)
    data.append('document_type', documentType)
    if (supplierId) data.append('supplier_id', supplierId)
    if (transactionId) data.append('transaction_id', transactionId)
    return request<any>('/documents', { method: 'POST', body: data })
  },
  extractDocument: (file: File, documentType: string) => {
    const data = new FormData()
    data.append('file', file)
    data.append('document_type', documentType)
    return request<any>('/extract', { method: 'POST', body: data })
  },

  // ── Analytics (PRD Sec15.7 - sub-endpoints) ─────────────────────────────
  analytics: () => request<Analytics>('/analytics'),
  analyticsOverview: () => request<{ total_assessments: number; high_risk_exposure: number; risk_distribution: { risk: string; count: number }[] }>('/analytics/overview'),
  analyticsRiskDistribution: () => request<{ risk: string; count: number }[]>('/analytics/risk-distribution'),
  analyticsFactors: () => request<{ factor: string; count: number }[]>('/analytics/factors'),
  analyticsModelPerformance: () => request<{ metrics: object; business_metrics: object; limitation: string }>('/analytics/model-performance'),

  // ── Audit log (PRD Sec15.6) ──────────────────────────────────────────────
  audit: (opts: { eventType?: string; entityType?: string; entityId?: string; actorId?: string; dateFrom?: string; dateTo?: string; limit?: number } = {}) => {
    const params = new URLSearchParams()
    if (opts.eventType) params.set('event_type', opts.eventType)
    if (opts.entityType) params.set('entity_type', opts.entityType)
    if (opts.entityId) params.set('entity_id', opts.entityId)
    if (opts.actorId) params.set('actor_id', opts.actorId)
    if (opts.dateFrom) params.set('date_from', opts.dateFrom)
    if (opts.dateTo) params.set('date_to', opts.dateTo)
    params.set('limit', String(opts.limit ?? 100))
    // PRD Sec15.6 - use /audit-events route
    return request<AuditEvent[]>(`/audit-events?${params.toString()}`)
  },

  // ── Razorpay integration (PRD Sec15.8) ──────────────────────────────────
  razorpayStatus: () => request<{ mode: string; configured: boolean; status: string }>('/integrations/razorpay/status'),
  razorpayTestConnection: () => request<{ status: string; http_status: number }>('/integrations/razorpay/test-connection', { method: 'POST' }),

  // ── Health ─────────────────────────────────────────────────────────────
  healthLive: () => fetch(`${base}/health/live`).then(r => r.json()) as Promise<{ status: string }>,
  healthReady: () => fetch(`${base}/health/ready`).then(r => r.json()) as Promise<{ status: string }>,
}
