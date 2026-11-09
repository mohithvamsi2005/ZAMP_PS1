import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { fixtureDashboard } from '../test/fixtures';
import { renderWithRouter, stubFetch, jsonResponse } from '../test/helpers';
import Overview from './Overview';

describe('Overview dashboard', () => {
  it('renders real metrics from the summary endpoint', async () => {
    stubFetch((url) => (url.endsWith('/dashboard/summary') ? jsonResponse(200, fixtureDashboard()) : jsonResponse(404, {})));
    const { getByTestId } = renderWithRouter(<Overview />);

    await waitFor(() => expect(getByTestId('metric-total')).toHaveTextContent('8'));
    expect(getByTestId('metric-completed')).toHaveTextContent('4');
    expect(getByTestId('metric-approved')).toHaveTextContent('1');
    expect(getByTestId('metric-review')).toHaveTextContent('2');
    expect(getByTestId('metric-rejected')).toHaveTextContent('1');
    expect(getByTestId('metric-failed')).toHaveTextContent('1');

    // Recent activity row from the fixture renders vendor + invoice links
    expect(screen.getAllByText('INV-DEMO-1001').length).toBeGreaterThan(0);
    expect(screen.getAllByText('ABC Industrial Supplies Pvt Ltd').length).toBeGreaterThan(0);
  });

  it('shows a real empty state when nothing is decided and nothing has failed', async () => {
    const dash = fixtureDashboard();
    dash.decisions = { APPROVE: 0, REVIEW: 0, REJECT: 0 };
    dash.decision_total = 0;
    dash.approval_rate = null;
    dash.review_queue = 0;
    dash.latest_failed_runs = [];
    dash.totals.failed_runs = 0;
    stubFetch((url) => (url.endsWith('/dashboard/summary') ? jsonResponse(200, dash) : jsonResponse(404, {})));
    const { findByText } = renderWithRouter(<Overview />);
    expect(await findByText('No decisions yet')).toBeInTheDocument();
    expect(await findByText('No failures')).toBeInTheDocument();
  });

  it('surfaces an error banner (with retry) when the summary call fails', async () => {
    stubFetch(() => jsonResponse(500, { detail: 'boom' }));
    const { findByRole, findAllByRole } = renderWithRouter(<Overview />);
    expect(await findByRole('alert')).toBeInTheDocument();
    expect((await findAllByRole('button', { name: /try again/i })).length).toBeGreaterThan(0);
  });
});
