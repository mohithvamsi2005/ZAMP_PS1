import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { stubFetch, jsonResponse } from '../test/helpers';
import { fixtureRunDetail, fixtureEvents } from '../test/fixtures';
import ProcessingRun from './ProcessingRun';

const RUN_ID = 'run-fixture-0001';

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/processing/${RUN_ID}`]}>
      <Routes>
        <Route path="/processing/:runId" element={<ProcessingRun />} />
        <Route path="/runs" element={<div>history-probe</div>} />
        <Route path="/invoices/:id" element={<div>invoice-probe</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function stubPage(getRunImpl: () => object) {
  return stubFetch((url) => {
    if (url.endsWith(`/api/runs/${RUN_ID}`)) return jsonResponse(200, getRunImpl());
    if (url.endsWith(`/api/runs/${RUN_ID}/events`)) return jsonResponse(200, fixtureEvents(8));
    return jsonResponse(404, { detail: 'not found' });
  });
}

afterEach(() => vi.useRealTimers());

describe('Processing run live view', () => {
  it('polls until the run completes, then stops polling', async () => {
    vi.useFakeTimers();
    let call = 0;
    const fetchMock = stubPage(() => {
      call += 1;
      return call <= 2 ? fixtureRunDetail({ status: 'RUNNING', decision: null }) : fixtureRunDetail();
    });

    renderPage();
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByText(/Live processing timeline/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await act(async () => { await vi.advanceTimersByTimeAsync(1750); });
    expect(screen.queryByText('Processed')).not.toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(1750); });
    expect(screen.getByText('Processed')).toBeInTheDocument();

    const terminal = fetchMock.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(fetchMock.mock.calls.length).toBe(terminal);
  });

  it('shows the outcome card and links to the invoice detail on completion', async () => {
    stubPage(() => fixtureRunDetail());
    renderPage();
    expect((await screen.findAllByText('REVIEW')).length).toBeGreaterThan(0);
    expect(await screen.findByText(/Open full invoice intelligence/)).toBeInTheDocument();
  });

  it('renders the retry action for FAILED runs and posts to the retry endpoint on click', async () => {
    const posted: string[] = [];
    const user = userEvent.setup();
    stubFetch((url, init) => {
      if (url.endsWith(`/api/runs/${RUN_ID}/retry`) && init?.method === 'POST') {
        posted.push(url);
        return jsonResponse(200, { run_id: RUN_ID, status: 'PENDING', message: 'Run reset and queued for retry.' });
      }
      if (url.endsWith(`/api/runs/${RUN_ID}`)) {
        return jsonResponse(200, fixtureRunDetail({ status: 'FAILED', decision: null, error_message: 'simulated extraction failure' }));
      }
      if (url.endsWith(`/api/runs/${RUN_ID}/events`)) return jsonResponse(200, fixtureEvents(6));
      return jsonResponse(404, { detail: 'not found' });
    });

    renderPage();
    const retryButton = await screen.findByRole('button', { name: /retry this run/i });
    await user.click(retryButton);
    await waitFor(() => expect(posted.length).toBeGreaterThan(0));
  });

  it('keeps the page alive with a degraded banner on network failure, then recovers on retry', async () => {
    let call = 0;
    stubFetch((url) => {
      call += 1;
      if (call <= 2) throw new TypeError('fetch failed'); // first load fails hard
      if (url.endsWith(`/api/runs/${RUN_ID}`)) return jsonResponse(200, fixtureRunDetail());
      if (url.endsWith(`/api/runs/${RUN_ID}/events`)) return jsonResponse(200, fixtureEvents(8));
      return jsonResponse(404, { detail: 'not found' });
    });
    renderPage();
    expect(await screen.findByText(/Connection interrupted/)).toBeInTheDocument();

    const retryBtn = screen.getByRole('button', { name: /retry now/i });
    await userEvent.setup().click(retryBtn);
    expect(await screen.findByText(/Live processing timeline/)).toBeInTheDocument();
  });

  it('shows the not-found state for an unknown run', async () => {
    stubFetch(() => jsonResponse(404, { detail: 'Processing run does-not-exist not found' }));
    renderPage();
    expect(await screen.findByRole('alert')).toHaveTextContent(/does not exist/i);
  });
});
