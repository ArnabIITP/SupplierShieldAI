import type { Assessment } from '../types'
import { RiskBadge } from './RiskBadge'
import { EmptyState } from './EmptyState'

const currency = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })

interface AssessmentTableProps {
  assessments: Assessment[]
  onSelect?: (a: Assessment) => void
  compact?: boolean
}

export function AssessmentTable({ assessments, onSelect, compact }: AssessmentTableProps) {
  if (!assessments.length) {
    return <EmptyState title="No cases need attention right now." description="High-risk assessments will appear here when detected." />
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Assessment</th>
          <th>Exposure</th>
          <th>Risk</th>
          <th>Recommendation</th>
          {!compact && <th>Open</th>}
        </tr>
      </thead>
      <tbody>
        {assessments.map(a => (
          <AssessmentRow key={a.id} assessment={a} onSelect={onSelect} compact={compact} />
        ))}
      </tbody>
    </table>
  )
}

function AssessmentRow({ assessment: a, onSelect, compact }: { assessment: Assessment; onSelect?: (a: Assessment) => void; compact?: boolean }) {
  return (
    <tr
      onClick={() => onSelect?.(a)}
      style={{ cursor: onSelect ? 'pointer' : 'default' }}
      className="assessment-row"
    >
      <td>
        <span className="assessment-id-link">
          <b>{a.id.slice(-6).toUpperCase()}</b>
        </span>
        <small style={{ display: 'block', color: '#6B7280', marginTop: 2 }}>
          {new Date(a.created_at).toLocaleDateString('en-IN')}
        </small>
      </td>
      <td>{currency.format(a.amount)}</td>
      <td>
        <RiskBadge risk={a.risk_category} score={a.risk_score} />
        <small style={{ display: 'block', marginTop: 2, color: '#6B7280' }}>{a.confidence}% confidence</small>
      </td>
      <td>{a.recommendation}</td>
      {!compact && (
        <td>
          <button
            className="link"
            onClick={e => { e.stopPropagation(); onSelect?.(a) }}
            style={{ fontSize: '.82rem' }}
          >
            View details &rarr;
          </button>
        </td>
      )}
    </tr>
  )
}