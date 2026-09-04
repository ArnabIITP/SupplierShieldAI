import { useState, useEffect } from 'react'
import { ShieldCheck, Eye, EyeOff } from 'lucide-react'
import { supabase } from '../api'

export function ResetPasswordPage({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [show, setShow] = useState(false)
  const [status, setStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)

  // PRD Sec4.3 - Supabase sends a recovery token in the URL hash
  // The supabase client picks it up automatically on mount
  useEffect(() => {
    if (!supabase) return
    const { data: listener } = supabase.auth.onAuthStateChange((event) => {
      if (event === 'PASSWORD_RECOVERY') {
        // User is now in password-recovery state - safe to update
      }
    })
    return () => listener.subscription.unsubscribe()
  }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setMessage('')
    if (password.length < 8) {
      setMessage('Password must be at least 8 characters.')
      return
    }
    if (password !== confirm) {
      setMessage('Passwords do not match.')
      return
    }
    setLoading(true)
    const { error } = await supabase!.auth.updateUser({ password })
    setLoading(false)
    if (error) {
      setStatus('error')
      setMessage(error.message)
    } else {
      setStatus('success')
      setTimeout(onDone, 2000)
    }
  }

  return (
    <main className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <div className="brand auth-brand">
          <ShieldCheck size={25} />
          <span>SupplierShield</span>
        </div>
        <p className="eyebrow">ACCOUNT SECURITY</p>
        <h1>Set a new password</h1>

        {status === 'success' ? (
          <p className="success">Password updated. Redirecting to sign in...</p>
        ) : (
          <div className="page-content">
            <label>
              New password
              <div className="password-field">
                <input
                  type={show ? 'text' : 'password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  minLength={8}
                  required
                  autoComplete="new-password"
                  placeholder="At least 8 characters"
                />
                <button type="button" className="icon-btn password-toggle" onClick={() => setShow(s => !s)}>
                  {show ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
            </label>
            <label>
              Confirm password
              <input
                type={show ? 'text' : 'password'}
                value={confirm}
                onChange={e => setConfirm(e.target.value)}
                minLength={8}
                required
                autoComplete="new-password"
              />
            </label>
            {message && <p className={status === 'error' ? 'error' : 'field-error'}>{message}</p>}
            <button className="primary" disabled={loading}>
              {loading ? 'Updating...' : 'Update password'}
            </button>
          </div>
        )}
      </form>
    </main>
  )
}
