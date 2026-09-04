import { useState } from 'react'
import { ShieldCheck, ArrowLeft } from 'lucide-react'
import { supabase } from '../api'

export function ForgotPasswordPage({ onBack }: { onBack: () => void }) {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    // PRD Sec4.2 - use Supabase Auth for password reset, no backend involvement
    const { error: err } = await supabase!.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/#/reset-password`,
    })
    setLoading(false)
    if (err) {
      setError(err.message)
    } else {
      setSent(true)
    }
  }

  return (
    <main className="auth-shell">
      <div className="auth-card">
        <div className="brand auth-brand">
          <ShieldCheck size={25} />
          <span>SupplierShield</span>
        </div>
        <p className="eyebrow">ACCOUNT RECOVERY</p>
        {sent ? (
          <div className="page-content">
            <h1>Check your email</h1>
            <p className="auth-note">
              If an account exists for <b>{email}</b>, a password reset link has been sent.
              The message may take a few minutes to arrive.
            </p>
            <button className="quiet auth-back" onClick={onBack}>
              <ArrowLeft size={14} /> Back to sign in
            </button>
          </div>
        ) : (
          <form onSubmit={submit}>
            <h1>Reset your password</h1>
            <p className="auth-note">
              Enter your account email and we'll send a reset link.
              We'll never reveal whether an account exists.
            </p>
            <label>
              Email address
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                autoComplete="email"
                placeholder="you@example.com"
              />
            </label>
            {error && <p className="error">{error}</p>}
            <button className="primary" disabled={loading}>
              {loading ? 'Sending...' : 'Send reset link'}
            </button>
            <button type="button" className="link auth-switch" onClick={onBack}>
              <ArrowLeft size={13} /> Back to sign in
            </button>
          </form>
        )}
      </div>
    </main>
  )
}
