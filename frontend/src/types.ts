export type Risk = 'Low' | 'Medium' | 'High' | 'Critical'

export interface RiskFactor {
  code: string
  title: string
  severity: Risk
  contribution: number
  evidence: string
  recommendation: string
}

export interface AiAnalysis {
  summary: string
  risk_interpretation: string
  key_risk_factors: { factor: string; evidence: string; severity: string; verification: string }[]
  missing_information: string[]
  recommended_actions: string[]
  uncertainty: string
  disclaimer: string
}

export interface Assessment {
  id: string
  supplier_id: string
  amount: number
  risk_score: number
  risk_category: Risk
  confidence: number
  recommendation: string
  anomaly_score: number
  factors: RiskFactor[]
  ai_status: string
  ai_analysis?: AiAnalysis | null
  /** SHAP feature attributions for the XGBoost model. Explains ML probability only — not the composite score. */
  shap_contributions?: Record<string, number> | null
  model_version: string
  ruleset_version: string
  created_at: string
}

export interface Supplier {
  id: string
  legal_name: string
  category: string
  contact: string
  city: string
  state: string
  business_age_years: number
  registration_identifier: string
  payment_beneficiary: string
  payment_reference_masked: string
  source: string
  notes?: string | null
  status: string
  created_at: string
}

export interface Dashboard {
  summary: {
    total_assessments: number
    by_risk: Record<Risk, number>
    amount_under_review: number
    awaiting_action: number
  }
  review_queue: Assessment[]
  recent_activity: AuditEvent[]
  risk_trend: RiskTrendPoint[]
}

export interface RiskTrendPoint {
  date: string
  Low: number
  Medium: number
  High: number
  Critical: number
}

export interface AuditEvent {
  id: string
  event_type: string
  entity_type: string
  entity_id: string
  description: string
  created_at: string
}

export interface VerificationItem {
  id: string
  title: string
  status: 'pending' | 'verified' | 'rejected' | 'not_applicable'
  reviewer_note?: string | null
  question?: string | null
  evidence?: string | null
}

export interface VerificationResult {
  assessment_id: string
  case_id?: string
  status: string
  items: VerificationItem[]
}

export interface Decision {
  id: string
  action: string
  reason: string
  created_at: string
}

export interface Analytics {
  risk_distribution: { risk: string; count: number }[]
  top_risk_factors: { factor: string; count: number }[]
  risk_trend: RiskTrendPoint[]
  decision_outcomes: Record<string, number>
  verification_outcomes: Record<string, number>
  total_assessments: number
  high_risk_exposure: number
  model_benchmark: Record<string, unknown>
}

export type Page = 'dashboard' | 'suppliers' | 'assessments' | 'verification' | 'analytics' | 'audit' | 'settings'
