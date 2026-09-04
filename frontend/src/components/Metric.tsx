interface MetricProps {
  label: string
  value: string
  icon?: React.ReactNode
  highlight?: 'ok' | 'warn' | 'danger'
  desc?: string
}

export function Metric({ label, value, highlight, desc }: MetricProps) {
  return (
    <div className={`metric${highlight ? ` ${highlight}` : ''}`}>
      <span className="metric-label">{label}</span>
      <span className="metric-value">{value}</span>
      {desc && <span className="metric-desc">{desc}</span>}
    </div>
  )
}
