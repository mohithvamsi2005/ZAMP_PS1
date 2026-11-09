import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { stubFetch, jsonResponse } from './test/helpers';
import App from './App';

const probe = (url: string) =>
  url.endsWith('/api/auth/status') ? jsonResponse(200, { required: false, authenticated: true }) : jsonResponse(200, {});

describe('Auth gate', () => {
  it('shows the app when the backend reports auth not required', async () => {
    stubFetch(probe);
    render(<App />);
    await waitFor(() => expect(screen.queryByRole('heading', { name: /sign in/i })).not.toBeInTheDocument());
    // The real shell renders the sidebar nav
    expect(screen.getByRole('link', { name: /Overview/ })).toBeInTheDocument();
  });

  it('shows the login screen when auth is required and the session is missing', async () => {
    stubFetch((url) => (url.endsWith('/api/auth/status') ? jsonResponse(200, { required: true, authenticated: false }) : jsonResponse(404, {})));
    render(<App />);
    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeInTheDocument();
  });

  it('unlocks the app after a successful login', async () => {
    let authed = false;
    stubFetch((url, init) => {
      if (url.endsWith('/api/auth/status')) return jsonResponse(200, { required: true, authenticated: authed });
      if (url.endsWith('/api/auth/login') && init?.method === 'POST') {
        authed = true;
        return jsonResponse(200, { required: true, authenticated: true });
      }
      return jsonResponse(200, {});
    });
    render(<App />);
    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/access password/i), { target: { value: 'operator-password' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => expect(screen.queryByRole('heading', { name: /sign in/i })).not.toBeInTheDocument());
    expect(screen.getByRole('link', { name: /Overview/ })).toBeInTheDocument();
  });

  it('shows a wrong-password error on rejected login', async () => {
    stubFetch((url, init) => {
      if (url.endsWith('/api/auth/status')) return jsonResponse(200, { required: true, authenticated: false });
      if (url.endsWith('/api/auth/login') && init?.method === 'POST') return jsonResponse(401, { detail: 'Incorrect password' });
      return jsonResponse(404, {});
    });
    render(<App />);
    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/access password/i), { target: { value: 'wrong-password' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/incorrect password/i);
  });
});
