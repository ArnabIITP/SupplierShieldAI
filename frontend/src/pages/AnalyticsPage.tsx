import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts'
import type { Analytics } from '../types'
import { EmptyState } from '../components/EmptyState'

const currency = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })

const RISK_COLORS: Record<string, string> = {
  Low: '#15803D',
  Medium: '#B45309',
  High: '#C2410C',
  Critical: '#B91C1C',
}

interface AnalyticsPageProps {
  analytics: Analytics | undefined
}

export function AnalyticsPage({ analytics }: AnalyticsPageProps) {
  if (!analytics) {
    return (
      <section className="panel">
        <EmptyState title="Loading analytics..." description="Fetching workspace analytics data." />
      </section>
    )
  }

  const { risk_distribution, top_risk_factors, risk_trend, decision_outcomes, verification_outcomes, total_assessments, high_risk_exposure, model_benchmark } = analytics

  const decisionData = Object.entries(decision_outcomes ?? {}).map(([action, count]) => ({
    action: action.replace('_', ' '),
    count,
  }))

  const verificationData = Object.entries(verification_outcomes ?? {}).map(([status, count]) => ({
    status: status.replace('_', ' '),
    count,
  }))

  const pieColors = ['#2563EB', '#15803D', '#B45309', '#C2410C', '#64748B']

  return (
    <div className="page-content">
      {/* Summary metrics */}
      <section className="metrics">
        <div className="metric">
          <div>
            <span>Total assessments</span>
            <strong>{total_assessments}</strong>
          </div>
        </div>
        <div className="metric metric-danger">
          <div>
            <span>High-risk exposure</span>
            <strong>{currency.format(high_risk_exposure ?? 0)}</strong>
          </div>
        </div>
        {risk_distribution.map(item => (
          <div key={item.risk} className="metric">
            <div>
              <span>{item.risk} risk</span>
              <strong>{item.count}</strong>
            </div>
          </div>
        ))}
      </section>

      <section className="two-col">
        {/* Risk distribution pie */}
        <div className="panel">
          <div className="panel-title">
            <div>
              <h2>Risk distribution</h2>
              <p>Product analytics - not a fraud finding.</p>
            </div>
          </div>
          {risk_distribution.some(d => d.count > 0) ? (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={risk_distribution}
                  dataKey="count"
                  nameKey="risk"
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  label={({ risk, count }) => count > 0 ? `${risk}: ${count}` : ''}
                >
                  {risk_distribution.map(entry => (
                    <Cell key={entry.risk} fill={RISK_COLORS[entry.risk] ?? '#64748B'} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState title="No assessment data" description="Create assessments to see the distribution." />
          )}
        </div>

        {/* Top risk factors */}
        <div className="panel">
          <div className="panel-title">
            <div>
              <h2>Top risk factors</h2>
              <p>Most frequently detected signals across all assessments.</p>
            </div>
          </div>
          {top_risk_factors.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={top_risk_factors} layout="vertical" margin={{ left: 20, right: 16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                <XAxis type="number" tick={{ fontSize: 11, fill: '#64748B' }} allowDecimals={false} />
                <YAxis type="category" dataKey="factor" width={160} tick={{ fontSize: 11, fill: '#475569' }} />
                <Tooltip />
                <Bar dataKey="count" fill="#2563EB" radius={[0, 2, 2, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState title="No factor data yet" description="Factors will appear after assessments are run." />
          )}
        </div>
      </section>

      {/* Risk trend */}
      {risk_trend && risk_trend.length > 0 && (
        <section className="panel chart-panel">
          <div className="panel-title">
            <div>
              <h2>Assessment risk trend</h2>
              <p>Risk distribution across recent assessments, by date.</p>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={220}>
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
        </section>
      )}

      <section className="two-col">
        {/* Decision outcomes */}
        {decisionData.length > 0 && (
          <div className="panel">
            <div className="panel-title">
              <div>
                <h2>Decision outcomes</h2>
                <p>Human decisions recorded against assessments.</p>
              </div>
            </div>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={decisionData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                <XAxis dataKey="action" tick={{ fontSize: 11, fill: '#64748B' }} />
                <YAxis tick={{ fontSize: 11, fill: '#64748B' }} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" fill="#1E293B" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Verification outcomes */}
        {verificationData.length > 0 && (
          <div className="panel">
            <div className="panel-title">
              <div>
                <h2>Verification outcomes</h2>
                <p>Case status distribution across verification workflows.</p>
              </div>
            </div>
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie data={verificationData} dataKey="count" nameKey="status" cx="50%" cy="50%" outerRadius={70} label={({ status }) => status}>
                  {verificationData.map((_, i) => (
                    <Cell key={i} fill={pieColors[i % pieColors.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>

      {/* Model benchmark */}
      {model_benchmark && Object.keys(model_benchmark).length > 0 && (
        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>ML model benchmark</h2>
              <p>Test-set evaluation metrics from the training pipeline. These are reproduced exactly from the model artifacts.</p>
            </div>
          </div>
          <div className="benchmark-grid">
            {Object.entries(model_benchmark).map(([key, value]) => (
              typeof value === 'number' || typeof value === 'string' ? (
                <div key={key} className="benchmark-item">
                  <span>{key.replace(/_/g, ' ')}</span>
                  <b>{typeof value === 'number' ? value.toFixed(4) : String(value)}</b>
                </div>
              ) : null
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
