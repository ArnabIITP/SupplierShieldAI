import type { Risk } from '../types'

const ICONS: Record<string, string> = {
  Low: '✓',
  Medium: '~',
  High: '!',
  Critical: '✕',
}

export function RiskBadge({ risk, score, size }: { risk: Risk; score?: number; size?: 'sm' | 'md' | 'lg' }) {
  return (
    <span className={`risk-badge risk-badge--${risk.toLowerCase()} ${size ? `risk-badge--${size}` : ''}`}>
      <span>{ICONS[risk]}</span>
      {risk}
    </span>
  )
}
