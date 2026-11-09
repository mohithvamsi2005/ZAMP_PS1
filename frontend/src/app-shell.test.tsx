import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { render } from '@testing-library/react';
import { stubFetch, jsonResponse } from './test/helpers';
import { AppShell } from './components/layout/AppShell';

function renderShell(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<div>overview-probe</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('App shell', () => {
  it('renders brand, the four primary nav targets and a live-health badge', async () => {
    stubFetch((url: string) => {
      if (url.endsWith('/health')) {
        return jsonResponse(200, {
          status: 'ok', service: 'zamp-invoice-intelligence', database: 'connected',
          llm_provider: 'openrouter', llm_model: 'nvidia/nemotron-3-ultra-550b-a55b:free',
        });
      }
      return jsonResponse(404, {});
    });

    renderShell('/');

    expect(screen.getByText('Zamp')).toBeInTheDocument();
    expect(screen.getByText('Invoice Intelligence')).toBeInTheDocument();

    // Nav targets exactly as specified (Overview / Invoices / Review Queue / Processing History)
    expect(screen.getByRole('link', { name: /Overview/ })).toHaveAttribute('href', '/');
    expect(screen.getByRole('link', { name: /^Invoices$/ })).toHaveAttribute('href', '/invoices');
    expect(screen.getByRole('link', { name: /Review Queue/ })).toHaveAttribute('href', '/review');
    expect(screen.getByRole('link', { name: /History/ })).toHaveAttribute('href', '/runs');

    await waitFor(() => expect(screen.getByText('Live')).toBeInTheDocument());
    expect(screen.getByText(/openrouter/)).toBeInTheDocument();
  });

  it('surfaces the offline state when the health probe fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(503, {})));
    renderShell('/');
    await waitFor(() => expect(screen.getByText('Offline')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /retry connection/i })).toBeInTheDocument();
  });
});
