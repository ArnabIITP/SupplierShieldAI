import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, X, RefreshCw, Trash2, CreditCard } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { api } from '../api'
import type { Assessment, Decision, Supplier } from '../types'
import { AssessmentTable } from '../components/AssessmentTable'
import { EmptyState } from '../components/EmptyState'
import { RiskBadge } from '../components/RiskBadge'

const currency = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })

const assessmentSchema = z.object({
  supplier_id: z.string().min(1, 'Select a supplier'),
  amount: z.coerce.number().min(1).max(100_000_000),
  currency: z.string().default('INR'),
  category: z.string().min(2).max(80),
  quantity: z.coerce.number().min(1),
  unit_price: z.coerce.number().min(1),
  payment_method: z.string().min(2).max(50),
  advance_percentage: z.coerce.number().min(0).max(100),
  delivery_days: z.coerce.number().min(0).max(3650),
  delivery_terms: z.string().min(2).max(200),
  quote_deviation_percent: z.coerce.number().min(-100).max(1000).default(0),
  missing_information_count: z.coerce.number().min(0).max(20).default(0),
  payment_destination_changed: z.boolean().default(false),
  document_mismatch: z.boolean().default(false),
})
type AssessmentFormData = z.infer<typeof assessmentSchema>

interface AssessmentsPageProps {
  assessments: Assessment[]
  suppliers: Supplier[]
  onSelect: (a: Assessment) => void
  canCreate?: boolean
}

export function AssessmentsPage({ assessments, suppliers, onSelect, canCreate = true }: AssessmentsPageProps) {
  const [showForm, setShowForm] = useState(false)
  const [filterRisk, setFilterRisk] = useState('')
  const [viewMode, setViewMode] = useState<'all' | 'priority'>('all')
  const qc = useQueryClient()

  const {
    register,
    handleSubmit,
    setValue,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<AssessmentFormData>({ resolver: zodResolver(assessmentSchema) })

  const [ocrMessage, setOcrMessage] = useState('')
  const ocrMutation = useMutation({
    mutationFn: (file: File) => api.extractDocument(file, 'business_document'),
    onSuccess: data => {
      setOcrMessage('Extracted! Check the form below.')
      if (data.extracted_fields?.amount) {
        const amt = parseFloat(data.extracted_fields.amount.replace(/[^0-9.]/g, ''))
        if (!isNaN(amt)) setValue('amount', amt)
      }
      if (data.extracted_fields?.category) setValue('category', data.extracted_fields.category)
      if (data.extracted_fields?.quantity) {
        const qty = parseInt(data.extracted_fields.quantity.replace(/[^0-9]/g, ''))
        if (!isNaN(qty)) setValue('quantity', qty)
      }
      if (data.extracted_fields?.unit_price) {
        const price = parseFloat(data.extracted_fields.unit_price.replace(/[^0-9.]/g, ''))
        if (!isNaN(price)) setValue('unit_price', price)
      }
      if (data.extracted_fields?.payment_method) setValue('payment_method', data.extracted_fields.payment_method)
      if (data.extracted_fields?.delivery_days) {
        const days = parseInt(data.extracted_fields.delivery_days.replace(/[^0-9]/g, ''))
        if (!isNaN(days)) setValue('delivery_days', days)
      }
      if (data.extracted_fields?.delivery_terms) setValue('delivery_terms', data.extracted_fields.delivery_terms)
      if (data.extracted_fields?.advance_percentage) {
        const adv = parseInt(data.extracted_fields.advance_percentage.replace(/[^0-9]/g, ''))
        if (!isNaN(adv)) setValue('advance_percentage', adv)
      }
      if (data.extracted_fields?.quote_deviation_percent) {
        const qd = parseFloat(data.extracted_fields.quote_deviation_percent.replace(/[^0-9.-]/g, ''))
        if (!isNaN(qd)) setValue('quote_deviation_percent', qd)
      }
      if (data.extracted_fields?.missing_information_count) {
        const mc = parseInt(data.extracted_fields.missing_information_count.replace(/[^0-9]/g, ''))
        if (!isNaN(mc)) setValue('missing_information_count', mc)
      }
      if (data.extracted_fields?.supplier) {
        const found = suppliers.find(s => s.legal_name.toLowerCase().includes(data.extracted_fields!.supplier!.toLowerCase()) || data.extracted_fields!.supplier!.toLowerCase().includes(s.legal_name.toLowerCase()))
        if (found) setValue('supplier_id', found.id)
      }
    },
    onError: (e: Error) => setOcrMessage(e.message)
  })

  const createMutation = useMutation({
    // PRD Ã‚Sec4.9 - no fake animation; show real loading until API responds
    mutationFn: (data: AssessmentFormData) => api.createAssessment(data),
    onSuccess: result => {
      qc.invalidateQueries({ queryKey: ['assessments'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setShowForm(false)
      reset()
      onSelect(result as Assessment)
    },
  })

  const filtered = (() => {
    let list = filterRisk ? assessments.filter(a => a.risk_category === filterRisk) : assessments
    if (viewMode === 'priority') {
      list = [...list].sort((a, b) => {
        const riskOrder = { Critical: 3, High: 2, Medium: 1, Low: 0 }
        const riskDiff = (riskOrder[b.risk_category as keyof typeof riskOrder] ?? 0) - (riskOrder[a.risk_category as keyof typeof riskOrder] ?? 0)
        if (riskDiff !== 0) return riskDiff
        const exposureDiff = b.amount - a.amount
        if (exposureDiff !== 0) return exposureDiff
        return b.confidence - a.confidence
      })
    } else {
      list = [...list].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    }
    return list
  })()

  return (
    <>
      {showForm && (
        <div className="modal">
          <form className="form" onSubmit={handleSubmit(data => createMutation.mutate(data))}>
            <div className="form-head">
              <div>
                <h2>Assess supplier transaction</h2>
                <p>Risk is a model estimate based on evidence supplied - not a fraud determination.</p>
              </div>
              <button type="button" className="quiet icon-btn" onClick={() => setShowForm(false)}><X size={18} /></button>
            </div>

            {createMutation.isPending ? (
              <div className="processing-steps">
                <div className="step active">
                  <span className="step-dot" />
                  <span>Running risk assessment - please wait...</span>
                </div>
                <p className="processing-note">The risk model, anomaly detection, and AI analysis are running. This takes 3-15 seconds.</p>
              </div>
            ) : (
              <>
                <div style={{ background: '#F0F9FF', padding: '12px 16px', margin: '0 24px 16px', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div>
                    <strong>... Auto-fill with OCR</strong>
                    <div style={{ fontSize: '0.85rem', color: '#64748B' }}>Upload an invoice to populate transaction details.</div>
                  </div>
                  <input 
                    type="file" 
                      accept="application/pdf,image/png,image/jpeg"
                      onChange={e => {
                        if (e.target.files?.[0]) ocrMutation.mutate(e.target.files[0])
                      }}
                      disabled={ocrMutation.isPending}
                    />
                    {ocrMessage && <span style={{ fontSize: '0.85rem', color: ocrMutation.isError ? '#ef4444' : '#16a34a', flex: 1, textAlign: 'right' }}>{ocrMessage}</span>}
                  </div>
                  <div className="form-grid">
                    <label className="wide">
                      Supplier
                      <select {...register('supplier_id')}>
                      <option value="">Select supplier...</option>
                      {suppliers.map(s => (
                        <option key={s.id} value={s.id}>{s.legal_name}</option>
                      ))}
                    </select>
                    {errors.supplier_id && <span className="field-error">{errors.supplier_id.message}</span>}
                  </label>
                  <label>
                    Amount (INR)
                    <input {...register('amount')} type="number" min={1} placeholder="480000" />
                    {errors.amount && <span className="field-error">{errors.amount.message}</span>}
                  </label>
                  <label>
                    Category
                    <input {...register('category')} placeholder="Industrial supplies" />
                    {errors.category && <span className="field-error">{errors.category.message}</span>}
                  </label>
                  <label>
                    Quantity
                    <input {...register('quantity')} type="number" min={1} placeholder="800" />
                    {errors.quantity && <span className="field-error">{errors.quantity.message}</span>}
                  </label>
                  <label>
                    Unit price (INR)
                    <input {...register('unit_price')} type="number" min={1} placeholder="600" />
                    {errors.unit_price && <span className="field-error">{errors.unit_price.message}</span>}
                  </label>
                  <label>
                    Advance %
                    <input {...register('advance_percentage')} type="number" min={0} max={100} placeholder="100" />
                    {errors.advance_percentage && <span className="field-error">{errors.advance_percentage.message}</span>}
                  </label>
                  <label>
                    Delivery days
                    <input {...register('delivery_days')} type="number" min={0} placeholder="7" />
                    {errors.delivery_days && <span className="field-error">{errors.delivery_days.message}</span>}
                  </label>
                  <label>
                    Quote deviation %
                    <input
                      {...register('quote_deviation_percent')}
                      type="number"
                      step="0.01"
                      defaultValue={0}
                      placeholder="0.00"
                    />
                    <span className="field-hint">Positive = above market price. e.g. 15.5 means 15.5% higher than standard</span>
                  </label>
                  <label>
                    Missing information count
                    <input {...register('missing_information_count')} type="number" min={0} defaultValue={0} />
                  </label>
                  <label>
                    Payment method
                    <input {...register('payment_method')} placeholder="Bank transfer" />
                    {errors.payment_method && <span className="field-error">{errors.payment_method.message}</span>}
                  </label>
                  <label className="wide">
                    Delivery terms
                    <input {...register('delivery_terms')} placeholder="Delivered" />
                    {errors.delivery_terms && <span className="field-error">{errors.delivery_terms.message}</span>}
                  </label>
                </div>
                <div className="checks">
                  <label>
                    <input {...register('payment_destination_changed')} type="checkbox" />
                    Payment destination recently changed
                  </label>
                  <label>
                    <input {...register('document_mismatch')} type="checkbox" />
                    Document fields mismatch detected
                  </label>
                </div>
                {createMutation.error && <p className="error">{(createMutation.error as Error).message}</p>}
                <div className="actions">
                  <button type="button" className="quiet" onClick={() => setShowForm(false)}>Cancel</button>
                  <button className="primary" disabled={isSubmitting || createMutation.isPending}>
                    Assess risk
                  </button>
                </div>
              </>
            )}
          </form>
        </div>
      )}

      <section className="panel">
        <div className="panel-title">
          <div>
            <h2>Assessment history</h2>
            <p>Risk estimates include explainable factors and a human-controlled action path.</p>
          </div>
                    <div className="panel-controls">
            <div className="view-toggle">
              <button className={viewMode === 'all' ? 'active' : ''} onClick={() => setViewMode('all')}>All assessments</button>
              <button className={viewMode === 'priority' ? 'active' : ''} onClick={() => setViewMode('priority')}>Priority queue</button>
            </div>
            <select value={filterRisk} onChange={e => setFilterRisk(e.target.value)} className="filter-select">
              <option value="">All risk levels</option>
              <option value="Critical">Critical</option>
              <option value="High">High</option>
              <option value="Medium">Medium</option>
              <option value="Low">Low</option>
            </select>
            <button className="primary" onClick={() => setShowForm(true)}>
              <Plus size={16} /> New assessment
            </button>
          </div>
        </div>
        <span className="count">{filtered.length} cases</span>
        {filtered.length === 0 ? (
          <EmptyState
            title={filterRisk ? `No ${filterRisk.toLowerCase()}-risk cases` : 'No assessments yet'}
            description={filterRisk ? 'Adjust the filter or create a new assessment.' : 'Select a supplier and submit a transaction to begin risk assessment.'}
            action={!filterRisk ? <button className="primary" onClick={() => setShowForm(true)}><Plus size={16} /> New assessment</button> : undefined}
          />
        ) : (
          <AssessmentTable assessments={filtered} onSelect={onSelect} />
        )}
      </section>
    </>
  )
}

// Full assessment detail panel used by AssessmentDetailPage
export function AssessmentDetailPanel({ assessment, onClose, canDecide = true }: { assessment: Assessment; onClose: () => void; canDecide?: boolean }) {
  const qc = useQueryClient()

  const aiQuery = useQuery({
    queryKey: ['ai-analysis', assessment.id],
    queryFn: () => api.getAiAnalysis(assessment.id),
    enabled: !assessment.ai_analysis,
  })

  const refreshAi = useMutation({
    mutationFn: () => api.refreshAiAnalysis(assessment.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ai-analysis', assessment.id] }),
  })

  const decisionsQuery = useQuery({
    queryKey: ['decisions', assessment.id],
    queryFn: () => api.getDecisions(assessment.id),
  })

  const verifyMutation = useMutation({
    mutationFn: () => api.startVerification(assessment.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['verification', assessment.id] }),
  })

  const decideMutation = useMutation({
    mutationFn: ({ action, reason }: { action: string; reason: string }) => api.decide(assessment.id, action, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['decisions', assessment.id] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      qc.invalidateQueries({ queryKey: ['assessments'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteAssessment(assessment.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['assessments'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      onClose()
    },
  })

  const razorpayMutation = useMutation({
    mutationFn: () => api.razorpayTestOrder(assessment.id),
  })
  const [decisionAction, setDecisionAction] = useState('maintain_hold')
  const [decisionReason, setDecisionReason] = useState('')
  const [decisionMsg, setDecisionMsg] = useState('')

  const analysis = assessment.ai_analysis ?? aiQuery.data?.analysis
  const aiStatus = assessment.ai_status ?? aiQuery.data?.status

  // PRD Ã‚Sec10.7 - Low<30, Medium<60, High<80, Critical >= 80
  const scoreColor = assessment.risk_score >= 80 ? '#B91C1C'
    : assessment.risk_score >= 60 ? '#C2410C'
    : assessment.risk_score >= 30 ? '#B45309'
    : '#15803D'

  return (
    <div className="detail-panel">
      <div className="detail-head">
        <div>
          <h2>Assessment {assessment.id.slice(-6).toUpperCase()}</h2>
          <p>{new Date(assessment.created_at).toLocaleString('en-IN')}</p>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button
            className="quiet danger-quiet icon-btn"
            title="Delete assessment"
            disabled={deleteMutation.isPending}
            onClick={() => {
              if (window.confirm('Delete this assessment? This action is permanent and will be recorded in the audit log.')) {
                deleteMutation.mutate()
              }
            }}
          >
            <Trash2 size={16} />
          </button>
          <button className="quiet icon-btn" onClick={onClose}><X size={18} /></button>
        </div>
      </div>

      <div className="assessment-hero">
        {/* Risk score gauge */}
        <div className="score-display">
          <div className="score-circle" style={{ borderColor: scoreColor }}>
            <span className="score-number" style={{ color: scoreColor }}>{assessment.risk_score}</span>
            <span className="score-denom">/100</span>
          </div>
          <div className="score-meta">
            <RiskBadge risk={assessment.risk_category} />
            <div className="score-detail">
              <span title="Evidence coverage indicator - reflects available risk signals assessed. Higher values indicate more signals were evaluated. This is not a calibrated probability.">
                Evidence Coverage: <b>{assessment.confidence}%</b> <span style={{fontSize:'0.75em',opacity:0.6}}>(heuristic)</span>
              </span>
              <span>Anomaly signal: <b>{assessment.anomaly_score}</b></span>
            </div>
          </div>
        </div>
        <div className="recommendation-block">
          <p className="eyebrow">RECOMMENDATION</p>
          <h3>{assessment.recommendation}</h3>
          <p className="muted">
            This is a model-generated risk estimate based on available information and is not a determination of fraud or misconduct.
          </p>
          <div className="version-badges">
            <span>{assessment.model_version}</span>
            <span>{assessment.ruleset_version}</span>
          </div>
        </div>
      </div>

      {/* Risk factors */}
      {assessment.factors.length > 0 && (
        <div className="detail-section">
          <h3>Risk factors</h3>
          <div className="factor-list">
            {assessment.factors.map(f => (
              <div key={f.code} className={`factor-item factor-${f.severity.toLowerCase()}`}>
                <div className="factor-header">
                  <b>{f.title}</b>
                  <RiskBadge risk={f.severity} size="sm" />
                  <span className="contribution">+{f.contribution} pts</span>
                </div>
                <p className="factor-evidence">{f.evidence}</p>
                <p className="factor-rec"><strong>Verification:</strong> {f.recommendation}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* SHAP Feature Attribution - explains XGBoost model probability only */}
      {assessment.shap_contributions && Object.keys(assessment.shap_contributions).length > 0 && (
        <div className="detail-section">
          <h3>Model explanation (XGBoost)</h3>
          <p className="muted" style={{marginBottom:'0.75rem'}}>
            This shows the XGBoost model's internal feature attributions for this assessment.
            It explains the <strong>ML model probability only</strong> — not the deterministic
            rule score, the anomaly signal, or the final composite risk score.
          </p>
          <div className="shap-bars">
            {Object.entries(assessment.shap_contributions)
              .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
              .slice(0, 6)
              .map(([name, val]) => (
              <div key={name} className="shap-row">
                <span className="shap-label">{name.replace(/_/g,' ')}</span>
                <div className="shap-bar-wrap">
                  <div
                    className={`shap-bar ${val >= 0 ? 'shap-pos' : 'shap-neg'}`}
                    style={{width: `${Math.min(100, Math.abs(val) * 300)}%`}}
                  />
                </div>
                <span className="shap-val">{val >= 0 ? '+' : ''}{val.toFixed(3)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Score formula */}
      <details className="detail-section score-formula-details">
        <summary style={{cursor:'pointer',fontWeight:600,marginBottom:'0.5rem'}}>
          How this score is calculated
        </summary>
        <div className="score-formula-body">
          <p><strong>Deterministic rule score:</strong> {assessment.factors.reduce((s,f)=>s+f.contribution,0)} pts (capped at 88)</p>
          <p><strong>XGBoost model probability:</strong> shown in Model explanation above</p>
          <p><strong>IsolationForest anomaly signal:</strong> {assessment.anomaly_score} / 100</p>
          <p><strong>Composite formula (weights selected on validation data):</strong></p>
          <code style={{display:'block',background:'var(--surface)',padding:'0.5rem 0.75rem',borderRadius:4,fontSize:'0.85em',margin:'0.5rem 0'}}>
            score = max(8, min(100, round(rule * W_rule + ml_prob * 100 * W_ml + anomaly * W_anomaly)))
          </code>
          <p className="muted" style={{fontSize:'0.8em'}}>
            Exact weights are loaded from <code>train_config.json</code> and selected using minimum
            expected decision cost on the validation set. SHAP is used only to annotate evidence
            text and display the model explanation above — it is never added to the risk score.
          </p>
        </div>
      </details>
      {/* AI Analysis */}
      <div className="detail-section">
        <div className="section-head">
          <h3>AI risk analysis</h3>
          <button
            className="link icon-text"
            onClick={() => refreshAi.mutate()}
            disabled={refreshAi.isPending}
          >
            <RefreshCw size={14} /> {refreshAi.isPending ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
        <p className="ai-status">Status: {aiStatus}</p>
        {analysis ? (
          <div className="ai-analysis">
            <div className="ai-section">
              <b>Summary</b>
              <p>{analysis.summary}</p>
            </div>
            <div className="ai-section">
              <b>Risk interpretation</b>
              <p>{analysis.risk_interpretation}</p>
            </div>
            {analysis.recommended_actions && analysis.recommended_actions.length > 0 && (
              <div className="ai-section">
                <b>Recommended actions</b>
                <ul>
                  {analysis.recommended_actions.map((action, i) => <li key={i}>{action}</li>)}
                </ul>
              </div>
            )}
            {analysis.missing_information && analysis.missing_information.length > 0 && (
              <div className="ai-section">
                <b>Missing information</b>
                <ul>
                  {analysis.missing_information.map((item, i) => <li key={i}>{item}</li>)}
                </ul>
              </div>
            )}
            <div className="ai-disclaimer">
              <small>{analysis.disclaimer}</small>
            </div>
          </div>
        ) : aiQuery.isLoading ? (
          <div className="skeleton-row" />
        ) : (
          <p className="muted">AI explanation temporarily unavailable. Risk score remains valid.</p>
        )}
      </div>

      {/* Verification status */}
      <div className="detail-section">
        <div className="section-head">
          <h3>Verification</h3>
        </div>
        <VerificationStatus assessmentId={assessment.id} onRequestVerification={() => verifyMutation.mutate()} verifyPending={verifyMutation.isPending} />
      </div>

      {/* Decision â€” only accessible once verification is resolved or not needed */}
      <div className="detail-section">
        <h3>Decision</h3>
        <DecisionSection
          assessmentId={assessment.id}
          decisionsQuery={decisionsQuery}
          decideMutation={decideMutation}
          decisionAction={decisionAction}
          setDecisionAction={setDecisionAction}
          decisionReason={decisionReason}
          setDecisionReason={setDecisionReason}
          decisionMsg={decisionMsg}
          setDecisionMsg={setDecisionMsg}
        />
      </div>

      {/* Razorpay test payment â€” shown after an approved decision */}
      {decisionsQuery.data?.some(d => d.action === 'approve') && (
        <div className="detail-section razorpay-section">
          <div className="section-head">
            <h3>Payment simulation</h3>
          </div>
          <p className="muted">Transaction approved. Create a Razorpay sandbox test order to simulate the payment handoff. No real payment is initiated.</p>
          <button
            className="primary"
            onClick={() => razorpayMutation.mutate()}
            disabled={razorpayMutation.isPending}
          >
            <CreditCard size={15} />
            {razorpayMutation.isPending ? 'Creating...' : 'Create test order (sandbox)'}
          </button>
          {razorpayMutation.data && (
            <div className="razorpay-result">
              <p className="success">Test order created successfully.</p>
              <dl className="settings-dl">
                <dt>Order ID</dt><dd><code>{razorpayMutation.data.order_id}</code></dd>
                <dt>Amount</dt><dd>INR {(razorpayMutation.data.amount / 100).toLocaleString('en-IN')}</dd>
                <dt>Status</dt><dd>{razorpayMutation.data.status}</dd>
              </dl>
              <p className="muted"><strong>Note:</strong> This is a Razorpay sandbox test order. No real payment is initiated or blocked.</p>
            </div>
          )}
          {razorpayMutation.isError && (
            <p className="error">Could not create test order. Check that Razorpay test credentials are configured in Settings.</p>
          )}
        </div>
      )}
    </div>
  )
}

// Verification status widget â€” shows current state, exposes Request button only when no case exists
function VerificationStatus({ assessmentId, onRequestVerification, verifyPending }: {
  assessmentId: string
  onRequestVerification: () => void
  verifyPending: boolean
}) {
  const verQuery = useQuery({
    queryKey: ['verification', assessmentId],
    queryFn: () => api.getVerificationByAssessment(assessmentId),
    retry: false,
  })

  if (verQuery.isLoading) return <div className="skeleton-row" />

  const caseData = verQuery.data
  const caseStatus = caseData?.status

  if (!caseData || !caseStatus) {
    return (
      <div>
        <p className="muted">No verification case for this assessment. You can request one if there are risk factors that need evidence gathering.</p>
        <button className="decision" onClick={onRequestVerification} disabled={verifyPending} style={{ marginTop: 8 }}>
          {verifyPending ? 'Generating checklist...' : 'Request verification'}
        </button>
      </div>
    )
  }

  const items = caseData.items ?? []
  const done = items.filter(i => i.status === 'verified' || i.status === 'rejected' || i.status === 'not_applicable').length
  const total = items.length

  const statusColor = caseStatus === 'closed' ? '#15803D' : caseStatus === 'open' ? '#B45309' : '#1D4ED8'

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <span style={{ fontWeight: 600, color: statusColor, textTransform: 'uppercase', fontSize: '0.8rem' }}>
          {caseStatus.replace('_', ' ')}
        </span>
        {total > 0 && <span className="muted">{done}/{total} items resolved</span>}
      </div>
      {caseStatus !== 'closed'
        ? <div className="decision-warning">
            <span>&#9888;</span>
            <div>
              <strong>Active verification in progress.</strong> Go to the <strong>Verification</strong> page to review evidence and update item status. Decisions are locked until verification is closed.
            </div>
          </div>
        : <div className="decision-locked">
            <span className="lock-icon">&#9989;</span>
            <div>
              <strong>Verification closed.</strong> All {total} checks have been resolved. You may now record a final decision below.
            </div>
          </div>
      }
    </div>
  )
}

// Decision section â€” aware of verification case state
function DecisionSection({ assessmentId, decisionsQuery, decideMutation, decisionAction, setDecisionAction, decisionReason, setDecisionReason, decisionMsg, setDecisionMsg }: {
  assessmentId: string
  decisionsQuery: ReturnType<typeof useQuery<Decision[]>>
  decideMutation: ReturnType<typeof useMutation<Decision, Error, { action: string; reason: string }>>
  decisionAction: string
  setDecisionAction: (v: string) => void
  decisionReason: string
  setDecisionReason: (v: string) => void
  decisionMsg: string
  setDecisionMsg: (v: string) => void
}) {
  const verQuery = useQuery({
    queryKey: ['verification', assessmentId],
    queryFn: () => api.getVerificationByAssessment(assessmentId),
    retry: false,
  })

  const caseStatus = verQuery.data?.status
  const verificationBlocking = caseStatus && caseStatus !== 'closed'

  const decisions = decisionsQuery.data ?? []
  const finalDecision = decisions.find(d => d.action === 'approve' || d.action === 'reject')

  if (decisions.length > 0) {
    return (
      <>
        <div className="decisions-list">
          {decisions.map(d => (
            <div key={d.id} className="decision-record">
              <span className={`badge badge-decision badge-${d.action}`}>{d.action.replace(/_/g, ' ')}</span>
              <span>{d.reason}</span>
              <small>{new Date(d.created_at).toLocaleString('en-IN')}</small>
            </div>
          ))}
        </div>
        {finalDecision && (
          <div className="decision-locked">
            <span className="lock-icon">&#128274;</span>
            <div>
              <strong>Decision locked - {finalDecision.action.toUpperCase()}</strong>
              <p>Recorded on {new Date(finalDecision.created_at).toLocaleString('en-IN')}. This decision is final and cannot be changed in SupplierShield. Any reversal requires a new assessment.</p>
            </div>
          </div>
        )}
        {!finalDecision && !verificationBlocking && (
          <DecisionForm
            decisionAction={decisionAction}
            setDecisionAction={setDecisionAction}
            decisionReason={decisionReason}
            setDecisionReason={setDecisionReason}
            decisionMsg={decisionMsg}
            setDecisionMsg={setDecisionMsg}
            decideMutation={decideMutation}
          />
        )}
      </>
    )
  }

  if (verificationBlocking) {
    return (
      <p className="muted" style={{ fontStyle: 'italic' }}>
        Decisions are locked while verification is active. Resolve all checklist items in the Verification page first.
      </p>
    )
  }

  return (
    <DecisionForm
      decisionAction={decisionAction}
      setDecisionAction={setDecisionAction}
      decisionReason={decisionReason}
      setDecisionReason={setDecisionReason}
      decisionMsg={decisionMsg}
      setDecisionMsg={setDecisionMsg}
      decideMutation={decideMutation}
    />
  )
}

function DecisionForm({ decisionAction, setDecisionAction, decisionReason, setDecisionReason, decisionMsg, setDecisionMsg, decideMutation }: {
  decisionAction: string
  setDecisionAction: (v: string) => void
  decisionReason: string
  setDecisionReason: (v: string) => void
  decisionMsg: string
  setDecisionMsg: (v: string) => void
  decideMutation: ReturnType<typeof useMutation<Decision, Error, { action: string; reason: string }>>
}) {
  return (
    <div className="decision-form">
      <select value={decisionAction} onChange={e => setDecisionAction(e.target.value)}>
        <option value="maintain_hold">Maintain hold</option>
        <option value="request_information">Request information</option>
        <option value="approve">Approve</option>
        <option value="reject">Reject</option>
      </select>
      <textarea value={decisionReason} onChange={e => setDecisionReason(e.target.value)} placeholder="Reason required (min 5 characters)" minLength={5} rows={3} style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border)', fontFamily: 'inherit', fontSize: '.9rem', resize: 'vertical' }} />
      {(decisionAction === 'approve' || decisionAction === 'reject') && (
        <p className="decision-warning">
          <span>&#9888;</span> <strong>{decisionAction === 'approve' ? 'Approving' : 'Rejecting'}</strong> this transaction is a final, irreversible action. It will be permanently logged.
        </p>
      )}
      <button
        className="decision"
        disabled={decideMutation.isPending || decisionReason.trim().length < 5}
        onClick={() => {
          decideMutation.mutate({ action: decisionAction, reason: decisionReason })
          setDecisionMsg('Decision recorded in the audit log.')
          setDecisionReason('')
        }}
      >
        {decideMutation.isPending ? 'Saving...' : 'Record decision'}
      </button>
      {decisionMsg && <small className="success">{decisionMsg}</small>}
    </div>
  )
}
