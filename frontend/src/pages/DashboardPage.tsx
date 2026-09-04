import { AlertTriangle, CheckCircle2, ClipboardCheck, FileSearch } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { Metric } from '../components/Metric'
import { AssessmentTable } from '../components/AssessmentTable'
import { EmptyState } from '../components/EmptyState'
import type { Assessment, Dashboard, Page } from '../types'

const currency = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })

const RISK_COLORS: Record<string, string> = {
  Low: '#15803D',
  Medium: '#B45309',
  High: '#C2410C',
  Critical: '#B91C1C',
}

interface DashboardPageProps {
  data: Dashboard
  assessments: Assessment[]
  onSelectAssessment: (a: Assessment) => void
  onPage: (page: Page) => void
}

export function DashboardPage({ data, assessments, onSelectAssessment, onPage }: DashboardPageProps) {
  const { summary, review_queue, recent_activity, risk_trend } = data

  return (
    <div className="page-content">
      {/* Metrics */}
      <div className="metrics">
        <Metric
          label="Total assessments"
          value={String(summary.total_assessments)}
          icon={<FileSearch size={20} />}
        />
        <Metric
          label="Awaiting action"
          value={String(summary.awaiting_action)}
          icon={<ClipboardCheck size={20} />}
          highlight={summary.awaiting_action > 0 ? 'warn' : undefined}
        />
        <Metric
          label="High-risk exposure"
          value={currency.format(summary.amount_under_review)}
          icon={<AlertTriangle size={20} />}
          highlight={summary.amount_under_review > 0 ? 'danger' : undefined}
        />
        <Metric
          label="Low risk"
          value={String(summary.by_risk?.Low ?? 0)}
          icon={<CheckCircle2 size={20} />}
          highlight="ok"
        />
        <Metric label="Medium risk" value={String(summary.by_risk?.Medium ?? 0)} />
        <Metric label="High risk" value={String(summary.by_risk?.High ?? 0)} highlight={summary.by_risk?.High > 0 ? 'warn' : undefined} />
        <Metric label="Critical" value={String(summary.by_risk?.Critical ?? 0)} highlight={summary.by_risk?.Critical > 0 ? 'danger' : undefined} />
      </div>

      {/* Risk trend chart */}
      {risk_trend && risk_trend.length > 0 && (
        <div className="panel chart-panel">
          <div className="panel-title">
            <div>
              <h2>Risk trend</h2>
              <p>Assessment risk distribution over time.</p>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={risk_trend} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#64748B' }} />
              <YAxis tick={{ fontSize: 11, fill: '#64748B' }} allowDecimals={false} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="Low" stackId="a" fill={RISK_COLORS.Low} />
              <Bar dataKey="Medium" stackId="a" fill={RISK_COLORS.Medium} />
              <Bar dataKey="High" stackId="a" fill={RISK_COLORS.High} />
              <Bar dataKey="Critical" stackId="a" fill={RISK_COLORS.Critical} radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Two-column: review queue + recent activity */}
      <div className="two-col">
        <div className="panel">
          <div className="panel-title">
            <div>
              <h2>Priority review queue</h2>
              <p>Ordered by risk score and financial exposure.</p>
            </div>
            <span className="count">{review_queue.length} cases</span>
          </div>
          {review_queue.length > 0 ? (
            <AssessmentTable assessments={review_queue} onSelect={onSelectAssessment} compact />
          ) : (
            <EmptyState
              title="No high-risk cases"
              description="No high-risk supplier transactions require attention."
            />
          )}
        </div>
        
        <div className="panel activity">
          <div className="panel-title">
            <div>
              <h2>Recent activity</h2>
              <p>Latest supplier risk events.</p>
            </div>
          </div>
          {recent_activity.length > 0 ? (
            recent_activity.map(a => (
              <div key={a.id} className="event">
                <div className="event-dot" />
                <div>
                  <b>{a.event_type}</b>
                  <p className="subtle" style={{ margin: '2px 0 0 0' }}>{a.description}</p>
                  <small>{new Date(a.created_at).toLocaleString('en-IN')}</small>
                </div>
              </div>
            ))
          ) : (
            <EmptyState title="No activity" description="No recent events." />
          )}
        </div>
      </div>

      <div className="panel">
        <div className="panel-title">
          <div>
            <h2>Recent assessments</h2>
            <p>Latest supplier transactions analysed.</p>
          </div>
        </div>
        {assessments.length === 0 ? (
          <EmptyState title="No assessments" description="Upload a supplier document to start." />
        ) : (
          assessments.map(a => (
            <article key={a.id} className="assessment-card" onClick={() => onSelectAssessment(a)}>
              <div>
                <span className={`risk-badge risk-badge--${a.risk_category.toLowerCase()}`}>
                  {a.risk_category} · {a.risk_score}/100
                </span>
                <h3>{a.recommendation}</h3>
                <p>
                  {a.factors[0]?.title || 'No elevated signals detected'} -{' '}
                  {a.factors[0]?.evidence || 'standard transaction evidence'}
                </p>
              </div>
              <div className="factor-meta">
                <b>{({ ai_complete: 'AI analysis ready', ai_pending: 'Analysis pending', ai_error: 'Analysis unavailable' } as Record<string, string>)[a.ai_status] ?? a.ai_status}</b>
                <small>
                  {a.model_version} · {a.ruleset_version}
                </small>
              </div>
            </article>
          ))
        )}
      </div>
    </div>
  )
}
