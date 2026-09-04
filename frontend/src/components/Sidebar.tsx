import { BarChart3, Building2, ClipboardCheck, FileSearch, LayoutDashboard, ScrollText, Settings } from 'lucide-react'
import type { Page } from '../types'

// New geometric brand mark: two rectangles forming a cross/grid motif
const BrandMark = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className="brand-mark">
    <rect x="2" y="10" width="20" height="4" rx="1" fill="#1B5E6E"/>
    <rect x="10" y="2" width="4" height="20" rx="1" fill="#1B5E6E"/>
    <rect x="6" y="6" width="12" height="12" rx="1" fill="none" stroke="rgba(27,94,110,0.6)" strokeWidth="1"/>
  </svg>
)

const navGroups: { label: string; items: { id: Page; label: string; icon: React.ReactNode }[] }[] = [
  {
    label: 'Overview',
    items: [
      { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard size={14} /> },
    ],
  },
  {
    label: 'Risk',
    items: [
      { id: 'assessments', label: 'Assessments', icon: <FileSearch size={14} /> },
      { id: 'suppliers', label: 'Suppliers', icon: <Building2 size={14} /> },
      { id: 'verification', label: 'Verification', icon: <ClipboardCheck size={14} /> },
      { id: 'analytics', label: 'Analytics', icon: <BarChart3 size={14} /> },
    ],
  },
  {
    label: 'Operations',
    items: [
      { id: 'audit', label: 'Audit Log', icon: <ScrollText size={14} /> },
    ],
  },
  {
    label: 'Account',
    items: [
      { id: 'settings', label: 'Settings', icon: <Settings size={14} /> },
    ],
  },
]

interface SidebarProps {
  page: Page
  onPage: (page: Page) => void
}

export function Sidebar({ page, onPage }: SidebarProps) {
  return (
    <aside>
      <div className="brand">
        <BrandMark />
        <div>
          <span className="brand-name">SupplierShield</span>
          <span className="brand-sub">Risk Platform</span>
        </div>
      </div>
      <nav>
        {navGroups.map(group => (
          <div className="nav-group" key={group.label}>
            <span className="nav-group-label">{group.label}</span>
            {group.items.map(item => (
              <button
                key={item.id}
                className={page === item.id ? 'active' : ''}
                onClick={() => onPage(item.id)}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
          </div>
        ))}
      </nav>
      <div className="sidebar-footer">
        <small>Workspace-scoped access</small>
        <small>Append-only audit trail</small>
      </div>
    </aside>
  )
}

// Ensure we export navItems flat for backward compatibility if needed
export const navItems = navGroups.flatMap(g => g.items)
