import { useCallback, useEffect, useState } from 'react';
import { RouterProvider } from 'react-router-dom';
import { router } from './router';
import { fetchAuthStatus } from './api';
import LoginPage from './pages/LoginPage';

const FUTURE = { v7_startTransition: true } as const;

export default function App() {
  const [gate, setGate] = useState<'loading' | 'authenticated' | 'login'>('loading');

  const probe = useCallback(async () => {
    try {
      const status = await fetchAuthStatus();
      setGate(status.required && !status.authenticated ? 'login' : 'authenticated');
    } catch {
      // Backend unreachable or older stack without auth — render the app and let
      // individual pages surface connectivity errors.
      setGate('authenticated');
    }
  }, []);

  useEffect(() => {
    probe();

    const onUnauthenticated = () => setGate('login');
    window.addEventListener('zamp:unauthenticated', onUnauthenticated);
    return () => window.removeEventListener('zamp:unauthenticated', onUnauthenticated);
  }, [probe]);

  if (gate === 'loading') {
    // Render a quiet blank rather than flash a login form for unauthenticated users
    return <div style={{ minHeight: '100dvh', background: '#10202b' }} aria-label="Loading" />;
  }
  if (gate === 'login') {
    return <LoginPage onAuthenticated={() => setGate('authenticated')} />;
  }

  return <RouterProvider router={router} future={FUTURE} />;
}
