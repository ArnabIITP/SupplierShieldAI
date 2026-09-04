import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle, XCircle, Clock, MinusCircle, Upload, Lock } from 'lucide-react'
import { api } from '../api'
import type { Assessment, VerificationItem } from '../types'
import { RiskBadge } from '../components/RiskBadge'
import { EmptyState } from '../components/EmptyState'

export interface VerificationPageProps {
  assessments: Assessment[]
  onSelect: (a: Assessment) => void
  /** PRD Sec5.11 - only owner/admin/reviewer can make decisions */
  canDecide?: boolean
}

export function VerificationPage({ assessments, onSelect, canDecide = true }: VerificationPageProps) {
  if (assessments.length === 0) {
    return (
      <section className="panel">
        <div className="panel-title">
          <div>
            <h2>Verification workbench</h2>
            <p>Gather evidence, mark checks, and record final case decisions.</p>
          </div>
        </div>
        <EmptyState
          title="No assessments to verify"
          description="Create assessments and request verification from the Assessments page."
        />
      </section>
    )
  }

  return (
    <section className="panel">
      <div className="panel-title">
        <div>
          <h2>Verification workbench</h2>
          <p>
            For each open case: gather supporting documents, mark each check as Verified or Rejected (irreversible),
            then record a final case decision once all checks are resolved.
          </p>
        </div>
        <span className="count">{assessments.length} cases</span>
      </div>
      <div className="verification-list">
        {assessments.map(a => (
          <VerificationCase key={a.id} assessment={a} onSelect={onSelect} canDecide={canDecide} />
        ))}
      </div>
    </section>
  )
}

// Status icons + colours
const STATUS_ICON: Record<string, React.ReactNode> = {
  verified: <CheckCircle size={16} color="#15803D" />,
  rejected: <XCircle size={16} color="#B91C1C" />,
  not_applicable: <MinusCircle size={16} color="#6B7280" />,
  pending: <Clock size={16} color="#B45309" />,
}
const STATUS_LABEL: Record<string, string> = {
  verified: 'Verified',
  rejected: 'Rejected',
  not_applicable: 'N/A',
  pending: 'Pending',
}
const FINAL_STATUSES = new Set(['verified', 'rejected', 'not_applicable'])

function VerificationCase({ assessment, onSelect, canDecide }: {
  assessment: Assessment
  onSelect: (a: Assessment) => void
  canDecide: boolean
}) {
  const qc = useQueryClient()
  const [caseNote, setCaseNote] = useState('')
  const [caseDecisionAction, setCaseDecisionAction] = useState('approve')
  const [uploadingItemId, setUploadingItemId] = useState<string | null>(null)

  const query = useQuery({
    queryKey: ['verification', assessment.id],
    queryFn: () => api.getVerificationByAssessment(assessment.id),
    retry: false,
  })

  const updateMutation = useMutation({
    mutationFn: ({ itemId, status, note }: { itemId: string; status: VerificationItem['status']; note?: string }) =>
      api.updateVerification(itemId, status, note),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['verification', assessment.id] }),
  })

  const uploadEvidenceMutation = useMutation({
    mutationFn: ({ file, itemId }: { file: File; itemId: string }) =>
      api.uploadDocument(file, 'verification_evidence', undefined, undefined),
    onSuccess: (_data, vars) => {
      setUploadingItemId(null)
      qc.invalidateQueries({ queryKey: ['verification', assessment.id] })
    },
  })

  const caseMutation = useMutation({
    mutationFn: ({ caseId, action, reason }: { caseId: string; action: string; reason: string }) =>
      api.verificationDecision(caseId, action, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['verification', assessment.id] })
      qc.invalidateQueries({ queryKey: ['assessments'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const caseData = query.data
  const items: VerificationItem[] = caseData?.items ?? []
  const caseId = caseData?.case_id

  const resolvedCount = items.filter(i => FINAL_STATUSES.has(i.status)).length
  const totalItems = items.length
  const allResolved = totalItems > 0 && resolvedCount === totalItems
  const caseStatus = caseData?.status

  const progressPct = totalItems > 0 ? Math.round((resolvedCount / totalItems) * 100) : 0

  return (
    <article className="verification-case">
      {/* Case header */}
      <div className="case-header" onClick={() => onSelect(assessment)} style={{ cursor: 'pointer' }}>
        <div>
          <b style={{ fontFamily: 'monospace' }}>{assessment.id.slice(-6).toUpperCase()}</b>
          <RiskBadge risk={assessment.risk_category} score={assessment.risk_score} />
        </div>
        <div className="case-meta">
          {totalItems > 0 && (
            <span className="progress-text">{resolvedCount}/{totalItems} resolved</span>
          )}
          <span className={`status-badge status-${caseStatus ?? 'not_started'}`}>
            {caseStatus?.replace('_', ' ') ?? 'not started'}
          </span>
        </div>
      </div>

      {/* Progress bar */}
      {totalItems > 0 && (
        <div className="verification-progress-bar">
          <div className="verification-progress-fill" style={{ width: `${progressPct}%` }} />
        </div>
      )}

      {query.isLoading && <div className="skeleton-row" style={{ margin: '12px 0' }} />}

      {/* No checklist yet */}
      {!query.isLoading && items.length === 0 && (
        <div className="case-empty">
          <small>No checklist generated yet.</small>
          {canDecide && (
            <button
              className="link"
              onClick={() => api.startVerification(assessment.id).then(() => qc.invalidateQueries({ queryKey: ['verification', assessment.id] }))}
            >
              Generate verification checklist
            </button>
          )}
        </div>
      )}

      {/* Checklist items */}
      {items.length > 0 && caseStatus !== 'closed' && (
        <div className="verification-items">
          {items.map((item: VerificationItem) => {
            const isLocked = FINAL_STATUSES.has(item.status)
            return (
              <div key={item.id} className={`verification-item-card ${isLocked ? 'item-locked' : ''}`}>
                <div className="item-card-header">
                  <div className="item-card-title">
                    {STATUS_ICON[item.status]}
                    <span>{item.title}</span>
                  </div>
                  <span className={`ver-status-badge ver-status-${item.status}`}>
                    {STATUS_LABEL[item.status]}
                  </span>
                </div>

                {/* Item description / question */}
                {item.question && (
                  <p className="item-question">{item.question}</p>
                )}
                {item.evidence && (
                  <p className="item-evidence muted">{item.evidence}</p>
                )}

                {/* Reviewer note (if any) */}
                {item.reviewer_note && (
                  <p className="item-reviewer-note">
                    <strong>Note:</strong> {item.reviewer_note}
                  </p>
                )}

                {/* Actions — locked after final status */}
                {isLocked ? (
                  <div className="item-locked-badge">
                    <Lock size={12} />
                    <small>This item is finalized and cannot be changed.</small>
                  </div>
                ) : canDecide && caseId ? (
                  <div className="item-actions">
                    {/* Evidence document upload */}
                    <label className="upload-evidence-btn" title="Upload supporting document">
                      <Upload size={13} />
                      {uploadingItemId === item.id ? 'Uploading...' : 'Attach evidence'}
                      <input
                        type="file"
                        accept="application/pdf,image/png,image/jpeg"
                        style={{ display: 'none' }}
                        disabled={uploadingItemId === item.id}
                        onChange={e => {
                          const f = e.target.files?.[0]
                          if (!f) return
                          setUploadingItemId(item.id)
                          uploadEvidenceMutation.mutate({ file: f, itemId: item.id })
                        }}
                      />
                    </label>

                    {/* Status action buttons */}
                    <div className="item-status-actions">
                      <button
                        className="btn-verify"
                        onClick={() => {
                          if (window.confirm('Mark this item as VERIFIED? This cannot be undone.')) {
                            updateMutation.mutate({ itemId: item.id, status: 'verified' })
                          }
                        }}
                        disabled={updateMutation.isPending}
                      >
                        <CheckCircle size={13} /> Verified
                      </button>
                      <button
                        className="btn-reject-item"
                        onClick={() => {
                          if (window.confirm('Mark this item as REJECTED? This cannot be undone.')) {
                            updateMutation.mutate({ itemId: item.id, status: 'rejected' })
                          }
                        }}
                        disabled={updateMutation.isPending}
                      >
                        <XCircle size={13} /> Rejected
                      </button>
                      <button
                        className="btn-na"
                        onClick={() => updateMutation.mutate({ itemId: item.id, status: 'not_applicable' })}
                        disabled={updateMutation.isPending}
                      >
                        <MinusCircle size={13} /> N/A
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      )}

      {/* Completed items summary (when case is closed) */}
      {caseStatus === 'closed' && items.length > 0 && (
        <div className="case-closed-summary">
          <CheckCircle size={16} color="#15803D" />
          <strong>Case closed.</strong>
          <span className="muted">{items.filter(i => i.status === 'verified').length} verified, {items.filter(i => i.status === 'rejected').length} rejected.</span>
        </div>
      )}

      {/* Final case decision — only available once all items are resolved and case is still open */}
      {allResolved && caseStatus !== 'closed' && canDecide && caseId && (
        <div className="case-decision-section">
          <h4>All checks resolved — record final case decision</h4>
          <p className="muted">
            This is the formal case-level decision. Once you choose Approve or Reject it is permanently recorded and cannot be reversed.
          </p>
          <div className="case-decision-form">
            <select value={caseDecisionAction} onChange={e => setCaseDecisionAction(e.target.value)}>
              <option value="approve">Approve — supplier checks passed</option>
              <option value="reject">Reject — supplier checks failed</option>
              <option value="maintain_hold">Maintain hold — needs further review</option>
            </select>
            <textarea
              placeholder="Summarise the evidence reviewed and reason for this decision (required)"
              rows={3}
              value={caseNote}
              onChange={e => setCaseNote(e.target.value)}
              style={{ resize: 'vertical' }}
            />
            {(caseDecisionAction === 'approve' || caseDecisionAction === 'reject') && (
              <p className="decision-warning">
                <span>&#9888;</span> <strong>{caseDecisionAction === 'approve' ? 'Approving' : 'Rejecting'}</strong> is final and irreversible. It will be permanently logged in the audit trail.
              </p>
            )}
            <button
              className={caseDecisionAction === 'reject' ? 'danger-quiet' : 'primary'}
              disabled={caseMutation.isPending || caseNote.trim().length < 10}
              onClick={() => {
                if (!window.confirm(`Confirm ${caseDecisionAction.toUpperCase()} for this verification case? This cannot be undone.`)) return
                caseMutation.mutate({ caseId: caseId!, action: caseDecisionAction, reason: caseNote })
              }}
            >
              {caseMutation.isPending ? 'Recording...' : `Record ${caseDecisionAction.replace('_', ' ')}`}
            </button>
            {caseMutation.isError && (
              <p className="error">{(caseMutation.error as Error).message}</p>
            )}
          </div>
        </div>
      )}
    </article>
  )
}