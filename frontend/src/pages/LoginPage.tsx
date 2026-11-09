import { useCallback, useState } from 'react';
import { ShieldCheck, LockKey, Eye, EyeSlash } from '@phosphor-icons/react';
import { loginWithPassword } from '../api/auth';

interface LoginPageProps {
  onAuthenticated: () => void;
}

export default function LoginPage({ onAuthenticated }: LoginPageProps) {
  const [password, setPassword] = useState('');
  const [show, setShow] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await loginWithPassword(password);
      if (result.authenticated) {
        onAuthenticated();
        return;
      }
      setError('That password was not accepted.');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Login failed';
      setError(/401|Incorrect|required/i.test(message) ? 'Incorrect password' : 'Cannot reach the backend — try again shortly.');
    } finally {
      setSubmitting(false);
    }
  }, [password, submitting, onAuthenticated]);

  return (
    <main className="login-screen" aria-labelledby="login-title">
      <form className="login-card" onSubmit={submit} aria-label="Sign in to Zamp Invoice Intelligence">
        <div className="login-brand">
          <div className="brand-mark" aria-hidden="true" style={{ width: 44, height: 44, borderRadius: 12 }}>
            <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M7 3h7l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
              <path d="M14 3v5h5" />
            </svg>
          </div>
          <div>
            <div className="login-brand-name">Zamp</div>
            <div className="login-brand-sub">Invoice Intelligence</div>
          </div>
        </div>

        <h1 id="login-title" className="login-title">Sign in</h1>
        <p className="login-sub">This console processes invoice PDFs through the extraction → matching → decision pipeline. Access is restricted to authorised operators.</p>

        <div className="field">
          <label htmlFor="password">Access password</label>
          <div className="password-wrap">
            <LockKey size={16} weight="duotone" aria-hidden="true" className="password-lock" />
            <input
              id="password"
              className="input password-input"
              type={show ? 'text' : 'password'}
              autoComplete="current-password"
              autoFocus
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Operator password"
            />
            <button
              type="button"
              className="password-toggle"
              aria-label={show ? 'Hide password' : 'Show password'}
              aria-pressed={show}
              onClick={() => setShow((s) => !s)}
            >
              {show ? <EyeSlash size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
            </button>
          </div>
        </div>

        {error && (
          <div className="error-box" role="alert">
            <span>{error}</span>
          </div>
        )}

        <button className="btn btn-primary login-submit" type="submit" disabled={submitting}>
          {submitting ? 'Verifying…' : 'Sign in'}
        </button>

        <p className="login-foot">
          <ShieldCheck size={12} weight="bold" aria-hidden="true" /> Sessions are HttpOnly, same-site scoped and expire after 12 hours.
        </p>
      </form>
    </main>
  );
}
