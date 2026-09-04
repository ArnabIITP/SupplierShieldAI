import { InboxIcon } from 'lucide-react'

interface EmptyStateProps {
  title: string
  description: string
  icon?: React.ReactNode
  action?: React.ReactNode
}

export function EmptyState({ title, description, icon, action }: EmptyStateProps) {
  return (
    <div className="empty">
      <div className="empty-icon">
        {icon || <InboxIcon size={18} />}
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action && <div className="empty-action" style={{ marginTop: 12 }}>{action}</div>}
    </div>
  )
}
