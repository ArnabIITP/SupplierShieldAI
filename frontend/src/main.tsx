import { useState, useEffect, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import { ShieldCheck, LogOut, Eye, EyeOff } from 'lucide-react'
import { api, supabase } from './api'
import type { Assessment, Page } from './types'
import { Sidebar } from './components/Sidebar'
import { DashboardPage } from './pages/DashboardPage'
import { SuppliersPage } from './pages/SuppliersPage'
import { AssessmentsPage, AssessmentDetailPanel } from './pages/AssessmentsPage'
import { VerificationPage } from './pages/VerificationPage'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { AuditPage } from './pages/AuditPage'
import { SettingsPage } from './pages/SettingsPage'
import { ForgotPasswordPage } from './pages/ForgotPasswordPage'
import { ResetPasswordPage } from './pages/ResetPasswordPage'
import './styles.css'

const client = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
  },
})

// ---------------------------------------------------------------------------
// Auth gate
// ---------------------------------------------------------------------------
type AuthMode = 'sign_in' | 'sign_up' | 'forgot_password' | 'reset_password'

function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<import('@supabase/supabase-js').Session | null>(null)
  const [ready, setReady] = useState(false)
  const [mode, setMode] = useState<AuthMode>('sign_in')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [message, setMessage] = useState('')
  const [msgType, setMsgType] = useState<'error' | 'success'>('error')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!supabase) { setReady(true); return }

    // PRD Sec4.3 - detect recovery token in URL hash
    const hash = window.location.hash
    if (hash.includes('type=recovery') || hash.includes('access_token')) {
      setMode('reset_password')
    }

    supabase.auth.getSession().then(async ({ data }) => {
      setSession(data.session)
      if (data.session) await bootstrapWorkspace()
      setReady(true)
    })

    const { data: listener } = supabase.auth.onAuthStateChange(async (_event, next) => {
      setSession(next)
      if (next) await bootstrapWorkspace()
    })
    return () => listener.subscription.unsubscribe()
  }, [])

  async function bootstrapWorkspace() {
    try {
      const result = await fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/v1/onboarding/complete`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${(await supabase!.auth.getSession()).data.session?.access_token}`,
        },
        body: JSON.stringify({ name: 'My workspace' }),
      })
      if (result.ok) {
        const ws = await result.json()
        localStorage.setItem('supplierShield.workspaceId', ws.id)
      }
    } catch { /* silently continue - workspace may already exist */ }
  }

  // PRD Sec4.1 - redirect already-authenticated users away from login
  if (session && (mode === 'sign_in' || mode === 'sign_up' || mode === 'forgot_password')) {
    return <>{children}</>
  }

  if (!supabase) {
    return (
      <main className="auth-shell">
        <div className="auth-card">
          <div className="auth-brand-compact">
            <svg width="22" height="22" viewBox="0 0 32 32" fill="none">
              <path d="M16 2L4 7v9c0 6.627 5.373 12 12 12s12-5.373 12-12V7L16 2z" fill="#1A3A6C"/>
              <path d="M11 16l3.5 3.5L21 13" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            <span className="brand-name">SupplierShield</span>
          </div>
          <p className="eyebrow">CONFIGURATION ERROR</p>
          <h1>Authentication not configured</h1>
          <p>Set <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> in <code>frontend/.env</code> and restart the dev server.</p>
        </div>
      </main>
    )
  }

  if (!ready) {
    return (
      <main className="loading">
        <svg width="36" height="36" viewBox="0 0 32 32" fill="none">
          <path d="M16 2L4 7v9c0 6.627 5.373 12 12 12s12-5.373 12-12V7L16 2z" fill="#1A3A6C"/>
          <path d="M11 16l3.5 3.5L21 13" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        <span>Checking secure workspace access...</span>
      </main>
    )
  }

  // PRD Sec4.2 - Forgot password page
  if (mode === 'forgot_password') {
    return <ForgotPasswordPage onBack={() => { setMode('sign_in'); setMessage('') }} />
  }

  // PRD Sec4.3 - Reset password page (triggered by recovery token in URL)
  if (mode === 'reset_password') {
    return <ResetPasswordPage onDone={() => { setMode('sign_in'); window.location.hash = '' }} />
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setMessage('')
    setLoading(true)
    const result =
      mode === 'sign_in'
        ? await supabase!.auth.signInWithPassword({ email, password })
        : await supabase!.auth.signUp({ email, password })
    setLoading(false)
    if (result.error) {
      setMsgType('error')
      setMessage(result.error.message)
    } else {
      setMsgType('success')
      setMessage(mode === 'sign_in'
        ? 'Signed in. Loading workspace...'
        : 'Account created. Check your email if verification is required.')
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-brand-panel">
        <div className="auth-panel-brand">
          <svg width="36" height="36" viewBox="0 0 32 32" fill="none">
            <path d="M16 2L4 7v9c0 6.627 5.373 12 12 12s12-5.373 12-12V7L16 2z" fill="#2E5FA3"/>
            <path d="M11 16l3.5 3.5L21 13" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
          <div className="brand-text">
            <span className="brand-name">SupplierShield</span>
            <span className="brand-tagline">Supplier Risk Platform</span>
          </div>
        </div>
        <p className="auth-tagline">Know the supplier before you trust the payment.</p>
        <p className="auth-sub">Supplier procurement risk management for Indian SMEs.</p>
        <ul className="auth-trust-list">
          <li><span className="auth-trust-check"><svg width="10" height="10" viewBox="0 0 12 12" fill="none"><path d="M2 6l3 3 5-5" stroke="#2E5FA3" strokeWidth="2" strokeLinecap="round"/></svg></span>Enterprise workspace isolation</li>
          <li><span className="auth-trust-check"><svg width="10" height="10" viewBox="0 0 12 12" fill="none"><path d="M2 6l3 3 5-5" stroke="#2E5FA3" strokeWidth="2" strokeLinecap="round"/></svg></span>Explainable risk scoring</li>
          <li><span className="auth-trust-check"><svg width="10" height="10" viewBox="0 0 12 12" fill="none"><path d="M2 6l3 3 5-5" stroke="#2E5FA3" strokeWidth="2" strokeLinecap="round"/></svg></span>Human-authorized decisions</li>
          <li><span className="auth-trust-check"><svg width="10" height="10" viewBox="0 0 12 12" fill="none"><path d="M2 6l3 3 5-5" stroke="#2E5FA3" strokeWidth="2" strokeLinecap="round"/></svg></span>Append-only audit trail</li>
        </ul>
      </div>
      <div className="auth-form-panel">
        <form className="auth-card" onSubmit={submit}>
          <div className="auth-brand-compact">
            <svg width="22" height="22" viewBox="0 0 32 32" fill="none">
              <path d="M16 2L4 7v9c0 6.627 5.373 12 12 12s12-5.373 12-12V7L16 2z" fill="#1A3A6C"/>
              <path d="M11 16l3.5 3.5L21 13" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            <span className="brand-name">SupplierShield</span>
          </div>
          <h1>{mode === 'sign_in' ? 'Sign in to your workspace' : 'Create your workspace'}</h1>
          <p className="subtle">Workspace-scoped access. All actions are audited.</p>
          <label>
            Email address
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} required autoComplete="email" />
          </label>
          <label>
            Password
            <div className="password-field">
              {/* PRD Sec4.1 - show/hide password control */}
              <input
                type={showPw ? 'text' : 'password'}
                value={password}
                onChange={e => setPassword(e.target.value)}
                minLength={8}
                required
                autoComplete={mode === 'sign_in' ? 'current-password' : 'new-password'}
              />
              <button type="button" className="password-toggle" onClick={() => setShowPw(s => !s)}>
                {showPw ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </label>
          {message && <p className={msgType}>{message}</p>}
          <button className="primary" disabled={loading} style={{width:'100%'}}>
            {loading ? 'Please wait...' : mode === 'sign_in' ? 'Sign in' : 'Create account'}
          </button>
          {/* PRD Sec4.1 - forgot password link */}
          {mode === 'sign_in' && (
            <button type="button" className="auth-switch" onClick={() => { setMode('forgot_password'); setMessage('') }}>
              Forgot password?
            </button>
          )}
          <button
            type="button"
            className="auth-switch"
            onClick={() => { setMode(mode === 'sign_in' ? 'sign_up' : 'sign_in'); setMessage('') }}
          >
            {mode === 'sign_in' ? 'Create an account' : 'Back to sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main application shell
// ---------------------------------------------------------------------------
function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const [selectedAssessment, setSelectedAssessment] = useState<Assessment | null>(null)
  const [workspaceRole, setWorkspaceRole] = useState<string>('owner') // default optimistic
  const qc = useQueryClient()

  // Load user role from /me on mount
  useEffect(() => {
    api.me().then(me => {
      const ws = me?.workspaces?.[0]
      if (ws) {
        setWorkspaceRole(ws.role)
        if (!localStorage.getItem('supplierShield.workspaceId')) {
          localStorage.setItem('supplierShield.workspaceId', ws.id)
          qc.invalidateQueries()
        }
      }
    }).catch(() => {})
  }, [qc])

  const hasWorkspace = !!localStorage.getItem('supplierShield.workspaceId')
  const dashboard = useQuery({ queryKey: ['dashboard'], queryFn: api.dashboard, enabled: hasWorkspace })
  const suppliers = useQuery({ queryKey: ['suppliers', ''], queryFn: () => api.suppliers(), enabled: hasWorkspace })
  const assessments = useQuery({ queryKey: ['assessments'], queryFn: () => api.assessments(), enabled: hasWorkspace })
  const analytics = useQuery({ queryKey: ['analytics'], queryFn: api.analytics, enabled: hasWorkspace })

  // PRD Sec5.5 - Sign out clears all state
  const handleSignOut = async () => {
    if (supabase) {
      await supabase.auth.signOut()
    }
    localStorage.removeItem('supplierShield.workspaceId')
    qc.clear()
    window.location.reload()
  }

  if (dashboard.isLoading || suppliers.isLoading) {
    return (
      <main className="loading">
        <svg width="36" height="36" viewBox="0 0 32 32" fill="none">
          <path d="M16 2L4 7v9c0 6.627 5.373 12 12 12s12-5.373 12-12V7L16 2z" fill="#1A3A6C"/>
          <path d="M11 16l3.5 3.5L21 13" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        <span>Loading your risk workspace...</span>
      </main>
    )
  }

  if (dashboard.error || suppliers.error) {
    const msg = ((dashboard.error || suppliers.error) as Error)?.message
    return (
      <main className="loading error-state">
        <svg width="36" height="36" viewBox="0 0 32 32" fill="none">
          <path d="M16 2L4 7v9c0 6.627 5.373 12 12 12s12-5.373 12-12V7L16 2z" fill="#1A3A6C"/>
          <path d="M11 16l3.5 3.5L21 13" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        <span>Unable to load workspace. {msg}</span>
        <small>Confirm the backend is running at {import.meta.env.VITE_API_URL || 'http://localhost:8000'}</small>
        <button className="quiet" onClick={handleSignOut}>Sign out and retry</button>
      </main>
    )
  }

  const data = dashboard.data!
  const allAssessments = assessments.data ?? []
  const allSuppliers = suppliers.data ?? []

  // PRD Sec3/Sec5.11 - role-aware capability flags
  const canCreate = ['owner', 'admin', 'analyst'].includes(workspaceRole)
  const canDecide = ['owner', 'admin', 'reviewer'].includes(workspaceRole)
  const canManageMembers = ['owner', 'admin'].includes(workspaceRole)

  function handleSelectAssessment(a: Assessment) {
    setSelectedAssessment(a)
    setPage('assessments')
  }

  const pageTitle: Record<Page, string> = {
    dashboard: 'Risk command centre',
    suppliers: 'Suppliers',
    assessments: 'Assessments',
    verification: 'Verification',
    analytics: 'Analytics',
    audit: 'Audit log',
    settings: 'Settings',
  }

  return (
    <div className="shell">
      <Sidebar page={page} onPage={p => { setPage(p); setSelectedAssessment(null) }} />
      <main>
        <header>
          <div className="page-header-left">
            <p className="breadcrumb">Workspace</p>
            <h1>{pageTitle[page]}</h1>
            <p className="page-subtitle">
              {page === 'dashboard'
                ? 'Monitor supplier exposure and act on cases that need attention.'
                : 'Workspace-scoped information for human-controlled risk decisions.'}
            </p>
          </div>
          <div className="header-controls">
            <span className="role-badge">{workspaceRole}</span>
            <button
              className="quiet icon-text sign-out-btn"
              onClick={handleSignOut}
              title="Sign out of your workspace"
            >
              <LogOut size={13} />
              Sign out
            </button>
          </div>
        </header>

        {/* PRD Sec4.10 - Assessment detail panel (no fake animation) */}
        {selectedAssessment && page === 'assessments' && (
          <AssessmentDetailPanel
            assessment={selectedAssessment}
            canDecide={canDecide}
            onClose={() => setSelectedAssessment(null)}
          />
        )}

        {page === 'dashboard' && (
          <DashboardPage
            data={data}
            assessments={allAssessments}
            onSelectAssessment={handleSelectAssessment}
            onPage={setPage}
          />
        )}
        {page === 'suppliers' && (
          <SuppliersPage
            assessments={allAssessments}
            onSelectAssessment={handleSelectAssessment}
            canCreate={canCreate}
          />
        )}
        {page === 'assessments' && (
          <AssessmentsPage
            assessments={allAssessments}
            suppliers={allSuppliers}
            onSelect={handleSelectAssessment}
            canCreate={canCreate}
          />
        )}
        {page === 'verification' && (
          <VerificationPage
            assessments={allAssessments}
            onSelect={handleSelectAssessment}
            canDecide={canDecide}
          />
        )}
        {page === 'analytics' && <AnalyticsPage analytics={analytics.data} />}
        {page === 'audit' && <AuditPage />}
        {page === 'settings' && <SettingsPage canManageMembers={canManageMembers} onSignOut={handleSignOut} />}
      </main>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={client}>
    <AuthGate>
      <App />
    </AuthGate>
  </QueryClientProvider>
)
