import { useEffect, useState } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { stubFetch, jsonResponse } from './test/helpers';
import { AppShell } from './components/layout/AppShell';

function renderShell(path: string, childElement: React.ReactElement = <div>overview-probe</div>) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={childElement} />
          <Route path="/invoices/:invoiceId" element={<div>detail-probe</div>} />
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
    expect(screen.getByRole('button', { name: /reset data/i })).toBeInTheDocument();
  });

  it('surfaces the offline state when the health probe fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(503, {})));
    renderShell('/');
    await waitFor(() => expect(screen.getByText('Offline')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /retry connection/i })).toBeInTheDocument();
  });

  it('requires confirmation to reset data and remounts child view with fresh values', async () => {
    let mountCount = 0;
    function CounterProbe() {
      const [num, setNum] = useState(0);
      useEffect(() => {
        mountCount += 1;
        setNum(mountCount);
      }, []);
      return <div data-testid="mount-count">{num}</div>;
    }

    const resetCalls: string[] = [];
    stubFetch((url: string, init?: RequestInit) => {
      if (url.endsWith('/health')) {
        return jsonResponse(200, {
          status: 'ok', service: 'zamp-invoice-intelligence', database: 'connected',
          llm_provider: 'llamacpp', llm_model: 'qwen2.5:1.5b',
        });
      }
      if (url.endsWith('/dashboard/reset') && init?.method === 'POST') {
        resetCalls.push(url);
        return jsonResponse(200, {
          status: 'ok', invoices: 3, runs: 0, vendors: 6, purchase_orders: 8, deleted_files: 2,
          message: 'Workspace reset to seeded baseline.',
        });
      }
      return jsonResponse(404, {});
    });

    renderShell('/', <CounterProbe />);
    expect(screen.getByTestId('mount-count')).toHaveTextContent('1');

    // Opening confirmation and cancelling does NOT invoke reset
    fireEvent.click(screen.getByRole('button', { name: /reset data/i }));
    expect(screen.getByRole('button', { name: /confirm reset/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(resetCalls).toHaveLength(0);
    expect(screen.getByTestId('mount-count')).toHaveTextContent('1');

    // Confirming calls POST /api/dashboard/reset and remounts the view
    fireEvent.click(screen.getByRole('button', { name: /reset data/i }));
    fireEvent.click(screen.getByRole('button', { name: /confirm reset/i }));

    await waitFor(() => expect(resetCalls).toHaveLength(1));
    await waitFor(() => expect(screen.getByTestId('mount-count')).toHaveTextContent('2'));
    expect(screen.getByRole('status')).toHaveTextContent(/3 sample invoices, 0 runs/i);
  });

  it('navigates from deleted invoice detail route to overview and surfaces errors cleanly', async () => {
    let shouldFail = true;
    stubFetch((url: string, init?: RequestInit) => {
      if (url.endsWith('/health')) {
        return jsonResponse(200, {
          status: 'ok', service: 'zamp-invoice-intelligence', database: 'connected',
          llm_provider: 'llamacpp', llm_model: 'qwen2.5:1.5b',
        });
      }
      if (url.endsWith('/dashboard/reset') && init?.method === 'POST') {
        if (shouldFail) {
          return jsonResponse(409, { detail: 'Cannot reset data while a processing run is queued or in progress.' });
        }
        return jsonResponse(200, {
          status: 'ok', invoices: 3, runs: 0, vendors: 6, purchase_orders: 8, deleted_files: 0,
          message: 'Workspace reset to seeded baseline.',
        });
      }
      return jsonResponse(404, {});
    });

    renderShell('/invoices/42');
    expect(screen.getByText('detail-probe')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /reset data/i }));
    fireEvent.click(screen.getByRole('button', { name: /confirm reset/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/in progress/i);
    expect(screen.getByText('detail-probe')).toBeInTheDocument();

    shouldFail = false;
    fireEvent.click(screen.getByRole('button', { name: /reset data/i }));
    fireEvent.click(screen.getByRole('button', { name: /confirm reset/i }));

    await waitFor(() => expect(screen.getByText('overview-probe')).toBeInTheDocument());
  });
});
