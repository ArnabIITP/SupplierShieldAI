import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { api } from '../api'
import { EmptyState } from '../components/EmptyState'
import type { AuditEvent } from '../types'

const EVENT_TYPES = [
  '', 'supplier.created', 'supplier.updated',
  'assessment.completed', 'assessment.ai_analysis_generated',
  'verification.requested', 'verification.updated',
  'decision.made', 'document.uploaded', 'workspace.created',
]

const ENTITY_TYPES = [
  '', 'supplier', 'assessment', 'verification_item',
  'document', 'workspace', 'payment',
]

export function AuditPage() {
  const [eventType, setEventType] = useState('')
  const [entityType, setEntityType] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  // PRD Sec15.6 - /audit-events with full filter set
  const { data, isLoading } = useQuery({
    queryKey: ['audit', eventType, entityType, dateFrom, dateTo],
    queryFn: () => api.audit({ eventType, entityType, dateFrom, dateTo, limit: 150 }),
  })

  const events: AuditEvent[] = data ?? []

  const fmt = (ts: string | Date) => {
    const d = new Date(ts)
    return d.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
  }

  const chipClass = (eventType: string) => {
    if (eventType.startsWith('assessment')) return 'chip-assessment'
    if (eventType.startsWith('verification')) return 'chip-verification'
    if (eventType.startsWith('decision')) return 'chip-decision'
    if (eventType.startsWith('document')) return 'chip-document'
    if (eventType.startsWith('supplier')) return 'chip-supplier'
    return 'chip-default'
  }

  return (
    <div className="page-content">
      {/* Filters - PRD Sec4.15 */}
      <section className="panel filter-bar">
        <div className="filter-row">
          <label>
            <span>Event type</span>
            <select value={eventType} onChange={e => setEventType(e.target.value)}>
              {EVENT_TYPES.map(t => (
                <option key={t} value={t}>{t || 'All events'}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Entity type</span>
            <select value={entityType} onChange={e => setEntityType(e.target.value)}>
              {ENTITY_TYPES.map(t => (
                <option key={t} value={t}>{t || 'All entities'}</option>
              ))}
            </select>
          </label>
          {/* PRD Sec4.15 - date filters */}
          <label>
            <span>From</span>
            <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
          </label>
          <label>
            <span>To</span>
            <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} />
          </label>
          {(eventType || entityType || dateFrom || dateTo) && (
            <button className="quiet" onClick={() => { setEventType(''); setEntityType(''); setDateFrom(''); setDateTo('') }}>
              Clear filters
            </button>
          )}
        </div>
      </section>

      <section className="panel">
        {isLoading ? (
          <div className="audit-loading">
            {Array.from({ length: 8 }, (_, i) => (
              <div key={i} className="audit-skeleton" />
            ))}
          </div>
        ) : events.length === 0 ? (
          <EmptyState
            icon={<Search size={32} />}
            title="No audit events found"
            description={
              eventType || entityType || dateFrom || dateTo
                ? 'Try adjusting the filters.'
                : 'All user actions and system events will appear here.'
            }
          />
        ) : (
          <table className="audit-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Event</th>
                <th>Entity</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {events.map(event => (
                <tr key={event.id}>
                  <td className="audit-time">{fmt(event.created_at)}</td>
                  <td>
                    <span className={`chip ${chipClass(event.event_type)}`}>
                      {event.event_type.replace(/\./g, ' › ')}
                    </span>
                  </td>
                  <td className="audit-entity">
                    <span className="muted">{event.entity_type}</span>
                    <code className="entity-id">{String(event.entity_id).slice(0, 8)}...</code>
                  </td>
                  <td>{event.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
