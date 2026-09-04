import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { LogOut, RefreshCw, CheckCircle, XCircle, Send } from 'lucide-react'
import { api } from '../api'

interface SettingsPageProps {
  /** PRD Sec4.16 - only owners/admins can manage members */
  canManageMembers?: boolean
  /** PRD Sec5.5 - sign-out triggered from Settings security section */
  onSignOut: () => void
}

export function SettingsPage({ canManageMembers = false, onSignOut }: SettingsPageProps) {
  const [testingRazorpay, setTestingRazorpay] = useState(false)
  const [razorpayTestResult, setRazorpayTestResult] = useState<{ status: string } | null>(null)

  // D9: Member invite state
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('analyst')

  const inviteMutation = useMutation({
    mutationFn: () => api.inviteWorkspaceMember(inviteEmail.trim(), inviteRole),
    onSuccess: () => setInviteEmail(''),
  })

  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/v1/health`).then(r => r.json()),
  })
  const razorpayStatus = useQuery({
    queryKey: ['razorpay-status'],
    queryFn: api.razorpayStatus,
  })
  const services = health.data?.services ?? {}

  const StatusDot = ({ ok }: { ok: boolean }) => (
    <span className={`status-dot ${ok ? 'status-ok' : 'status-off'}`} title={ok ? 'Available' : 'Unavailable'} />
  )

  const testRazorpay = async () => {
    setTestingRazorpay(true)
    setRazorpayTestResult(null)
    try {
      const result = await api.razorpayTestConnection()
      setRazorpayTestResult(result)
    } catch {
      setRazorpayTestResult({ status: 'error' })
    } finally {
      setTestingRazorpay(false)
    }
  }

  return (
    <div className="page-content settings">
      <h2>Workspace settings</h2>

      {/* PRD Sec4.16 - Workspace info */}
      <div className="settings-section">
        <h3>Workspace</h3>
        <p>
          Your workspace isolates all supplier data, assessments, and audit events.
          All operations are scoped to this workspace and are not shared with other organisations.
        </p>
        <dl className="settings-dl">
          <dt>Workspace ID</dt>
          <dd><code>{localStorage.getItem('supplierShield.workspaceId') || '–'}</code></dd>
        </dl>
      </div>

      {/* PRD Sec4.16 - Members (owner/admin only) */}
      {canManageMembers && (
        <div className="settings-section">
          <h3>Members</h3>
          <p>
            Workspace roles control what each member can do.
            Only owners and admins can invite, change roles, or deactivate members.
          </p>
          <table className="settings-table">
            <thead>
              <tr>
                <th>Role</th>
                <th>Permissions</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><span className="role-chip owner">Owner</span></td>
                <td>Full access - manage workspace, members, settings, and all decisions</td>
              </tr>
              <tr>
                <td><span className="role-chip admin">Admin</span></td>
                <td>Create suppliers, run assessments, manage members (not ownership transfer)</td>
              </tr>
              <tr>
                <td><span className="role-chip analyst">Analyst</span></td>
                <td>Create suppliers, upload documents, run assessments - cannot make final decisions</td>
              </tr>
              <tr>
                <td><span className="role-chip reviewer">Reviewer</span></td>
                <td>Review verification checklists and record decisions - read-only on everything else</td>
              </tr>
              <tr>
                <td><span className="role-chip viewer">Viewer</span></td>
                <td>Read-only: suppliers, assessments, reports</td>
              </tr>
            </tbody>
          </table>

          {/* D9: Invite form */}
          <div className="invite-form-section">
            <h4>Invite a new member</h4>
            <p className="muted">An invitation email will be sent via Supabase Auth. The member will be added to this workspace with the selected role on sign-up.</p>
            <div className="invite-form-row">
              <input
                type="email"
                placeholder="colleague@company.com"
                value={inviteEmail}
                onChange={e => setInviteEmail(e.target.value)}
                disabled={inviteMutation.isPending}
                style={{ flex: 1 }}
              />
              <select value={inviteRole} onChange={e => setInviteRole(e.target.value)} disabled={inviteMutation.isPending}>
                <option value="admin">Admin</option>
                <option value="analyst">Analyst</option>
                <option value="reviewer">Reviewer</option>
                <option value="viewer">Viewer</option>
              </select>
              <button
                className="primary"
                disabled={inviteMutation.isPending || inviteEmail.trim().length < 5}
                onClick={() => inviteMutation.mutate()}
              >
                <Send size={14} />
                {inviteMutation.isPending ? 'Sending...' : 'Send invite'}
              </button>
            </div>
            {inviteMutation.isSuccess && (
              <p className="success" style={{ marginTop: 8 }}>
                <CheckCircle size={14} /> Invitation sent to <strong>{inviteMutation.data?.email}</strong> as <strong>{inviteMutation.data?.role}</strong>.
              </p>
            )}
            {inviteMutation.isError && (
              <p className="error" style={{ marginTop: 8 }}>
                <XCircle size={14} /> {(inviteMutation.error as Error).message}
              </p>
            )}
          </div>
        </div>
      )}

      {/* PRD Sec4.16 - Risk policy */}
      <div className="settings-section">
        <h3>Risk policy</h3>
        <p>
          <b>Balanced (default)</b> - Risk estimates are explainable and escalation is human-controlled.
          The system prioritises a reasonable balance between missed risky transactions and unnecessary
          review of legitimate suppliers.
        </p>
        <dl className="settings-dl">
          <dt>Low risk</dt><dd>Score 0–29 - Proceed with standard controls</dd>
          <dt>Medium risk</dt><dd>Score 30–59 - Request verification</dd>
          <dt>High risk</dt><dd>Score 60–79 - Hold pending enhanced verification</dd>
          <dt>Critical risk</dt><dd>Score 80–100 - Hold pending enhanced verification</dd>
        </dl>
        <p className="muted">
          Thresholds are defined in PRD Sec10.7. Risk is a model estimate - not a fraud determination.
          AI recommends; humans remain accountable for consequential decisions.
        </p>
      </div>

      {/* PRD Sec4.16 - Model information */}
      <div className="settings-section">
        <h3>Model information</h3>
        <dl className="settings-dl">
          <dt>Risk model</dt><dd>Supplier risk v1 - local XGBoost classifier (trained on 30 k synthetic transactions)</dd>
          <dt>Anomaly detection</dt><dd>Isolation Forest - complementary signal, not a standalone classifier</dd>
          <dt>Explainability</dt><dd>SHAP TreeExplainer - feature contributions per assessment</dd>
          <dt>AI analyst</dt><dd>Google Gemini free tier - optional evidence synthesis layer</dd>
          <dt>OCR / Document</dt><dd>PyMuPDF (PDF) + Tesseract (images)</dd>
          <dt>Benchmark note</dt><dd>Model metrics are synthetic - never presented as real-world fraud performance</dd>
        </dl>
      </div>

      {/* PRD Sec4.16 - Integrations */}
      <div className="settings-section">
        <h3>Integration status</h3>
        <dl className="settings-dl">
          <dt><StatusDot ok={services.database === 'supabase-configured'} /> Database</dt>
          <dd>{services.database ?? 'Checking...'}</dd>
          <dt><StatusDot ok={services.ml_model === 'available'} /> ML model</dt>
          <dd>{services.ml_model ?? 'Checking...'}</dd>
          <dt><StatusDot ok={services.gemini === 'configured'} /> Gemini AI</dt>
          <dd>{services.gemini ?? 'Checking...'}</dd>
          <dt><StatusDot ok={services.api === 'available'} /> API</dt>
          <dd>{services.api ?? 'Checking...'}</dd>
        </dl>

        {/* PRD Sec4.16 - Razorpay integration card */}
        <div className="razorpay-card">
          <div className="razorpay-card-head">
            <div>
              <b>Razorpay</b>
              {razorpayStatus.data && (
                <span className={`integration-badge ${razorpayStatus.data.configured ? 'badge-ok' : 'badge-off'}`}>
                  {razorpayStatus.data.status}
                </span>
              )}
            </div>
            <button
              className="quiet"
              onClick={testRazorpay}
              disabled={testingRazorpay || !razorpayStatus.data?.configured}
            >
              {testingRazorpay ? <><RefreshCw size={13} className="spin" /> Testing...</> : 'Test connection'}
            </button>
          </div>
          {razorpayTestResult && (
            <p className={razorpayTestResult.status === 'ok' ? 'success' : 'error'}>
              {razorpayTestResult.status === 'ok'
                ? <><CheckCircle size={13} /> Connected to Razorpay Test sandbox</>
                : <><XCircle size={13} /> Connection failed - check Razorpay credentials</>}
            </p>
          )}
          <p className="muted">
            <b>Mode: Test only.</b> SupplierShield never initiates or blocks real payments.
            Razorpay is used only for test order creation in the Razorpay sandbox environment.
          </p>
        </div>
      </div>

      {/* PRD Sec4.16 / Sec5.5 - Security and sign out */}
      <div className="settings-section settings-security">
        <h3>Security</h3>
        <p>
          Authentication is handled by Supabase. Your credentials are never sent to the SupplierShield backend.
          All API calls require a valid short-lived JWT token.
        </p>
        <dl className="settings-dl">
          <dt>Authentication</dt><dd>Supabase Auth (JWT)</dd>
          <dt>Authorization</dt><dd>Server-side role enforcement on every request</dd>
          <dt>Data isolation</dt><dd>Workspace-scoped - cross-workspace access is blocked</dd>
          <dt>Document storage</dt><dd>Supabase private bucket - presigned download only</dd>
          <dt>Secrets</dt><dd>Backend only - never exposed to browser bundle</dd>
        </dl>
        {/* PRD Sec5.5 - Logout clears all local state */}
        <div className="sign-out-section">
          <p>Sign out to end your session and clear all local workspace state.</p>
          <button className="danger-quiet" onClick={onSignOut}>
            <LogOut size={15} />
            Sign out of workspace
          </button>
        </div>
      </div>
    </div>
  )
}
