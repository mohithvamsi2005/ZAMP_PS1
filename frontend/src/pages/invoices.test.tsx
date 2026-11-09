import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { stubFetch, renderWithRouter, jsonResponse } from '../test/helpers';
import Invoices from './Invoices';
import type { InvoiceListResponse } from '../types';

const fixtureList = (): InvoiceListResponse => ({
  total: 2,
  page: 1,
  page_size: 20,
  invoices: [
    {
      id: 4, invoice_number: 'INV-DEMO-1001', vendor_name: 'ABC Industrial Supplies Pvt Ltd',
      po_reference: 'PO-2044', total_amount: '60000.00', currency: 'INR',
      original_filename: 'demo_approve.pdf', file_sha256: 'abc123',
      created_at: '2026-11-09T15:50:27', last_run_id: 'run-1', last_run_status: 'COMPLETED', last_run_decision: 'REVIEW',
    },
    {
      id: 7, invoice_number: 'INV-777-OLD', vendor_name: 'XYZ Metals and Alloys',
      po_reference: 'PO-2045', total_amount: '120000.00', currency: 'INR',
      original_filename: 'xyz_old.pdf', file_sha256: 'def456',
      created_at: '2026-10-20T15:50:27', last_run_id: null, last_run_status: null, last_run_decision: null,
    },
  ],
});

describe('Invoices history page', () => {
  it('renders rows from the real API with decision and status pills', async () => {
    stubFetch((url) => (url.includes('/api/invoices') ? jsonResponse(200, fixtureList()) : jsonResponse(404, {})));
    renderWithRouter(<Invoices />);
    expect(await screen.findByText('INV-DEMO-1001')).toBeInTheDocument();
    expect(screen.getByText('XYZ Metals and Alloys')).toBeInTheDocument();
    expect(screen.getByText('REVIEW')).toBeInTheDocument();
    expect(screen.getAllByText('Processed').length).toBeGreaterThan(0); // badge + filter option
    expect(screen.getByText('₹60,000.00')).toBeInTheDocument();
  });

  it('passes search/decision/status filters to the backend as query params', async () => {
    const fn = stubFetch((url) => (url.includes('/api/invoices') ? jsonResponse(200, fixtureList()) : jsonResponse(404, {})));
    renderWithRouter(<Invoices />);
    await screen.findByText('INV-DEMO-1001');

    await userEvent.type(screen.getByLabelText(/search by invoice number/i), 'demo');
    await userEvent.selectOptions(screen.getByLabelText(/filter by decision/i), 'REVIEW');
    await userEvent.selectOptions(screen.getByLabelText(/filter by processing status/i), 'COMPLETED');

    await waitFor(() => {
      const urls = fn.mock.calls.map((c) => String(c[0]));
      expect(urls.some((u) => u.includes('search=demo'))).toBe(true);
      expect(urls.some((u) => u.includes('decision=REVIEW'))).toBe(true);
      expect(urls.some((u) => u.includes('status=COMPLETED'))).toBe(true);
    });
  });

  it('shows an empty state when the backend returns nothing', async () => {
    const empty = { total: 0, page: 1, page_size: 20, invoices: [] };
    stubFetch((url) => (url.includes('/api/invoices') ? jsonResponse(200, empty) : jsonResponse(404, {})));
    renderWithRouter(<Invoices />);
    expect(await screen.findByText('No invoices yet')).toBeInTheDocument();
  });

  it('shows an error box with retry when the list call fails', async () => {
    stubFetch(() => jsonResponse(500, {}));
    renderWithRouter(<Invoices />);
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });

  it('toggles sorting via the aria-sort column header', async () => {
    const fn = stubFetch((url) => (url.includes('/api/invoices') ? jsonResponse(200, fixtureList()) : jsonResponse(404, {})));
    renderWithRouter(<Invoices />);
    await screen.findByText('INV-DEMO-1001');
    const totalHeader = screen.getByRole('columnheader', { name: /total/i });
    await userEvent.click(totalHeader);
    await waitFor(() => {
      const urls = fn.mock.calls.map((c) => String(c[0]));
      expect(urls.some((u) => u.includes('sort_by=total_amount'))).toBe(true);
    });
  });
});
