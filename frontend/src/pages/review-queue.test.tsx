import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { stubFetch, renderWithRouter, jsonResponse } from '../test/helpers';
import ReviewQueue from './ReviewQueue';
import type { InvoiceListResponse } from '../types';

const reviewList = (count: number): InvoiceListResponse => ({
  total: count,
  page: 1,
  page_size: 50,
  invoices: Array.from({ length: count }, (_, i) => ({
    id: 100 + i,
    invoice_number: `INV-REVIEW-${100 + i}`,
    vendor_name: i % 2 === 0 ? 'ABC Industrial Supplies Pvt Ltd' : 'Sharma Electrical Components',
    po_reference: 'PO-2044',
    total_amount: '59000.00',
    currency: 'INR',
    original_filename: `review_${i}.pdf`,
    file_sha256: null,
    created_at: '2026-11-09T15:50:27',
    last_run_id: `run-${i}`,
    last_run_status: 'COMPLETED',
    last_run_decision: 'REVIEW',
  })),
});

describe('Review queue', () => {
  it('lists only REVIEW-decision invoices with company context and investigate links', async () => {
    stubFetch((url) => (url.includes('decision=REVIEW') ? jsonResponse(200, reviewList(2)) : jsonResponse(404, {})));
    renderWithRouter(<ReviewQueue />);

    expect(await screen.findByText('2 invoices waiting for review')).toBeInTheDocument();
    expect(screen.getByText('INV-REVIEW-100')).toBeInTheDocument();
    expect(screen.getByText('INV-REVIEW-101')).toBeInTheDocument();
    // Rows carry aria-label "Investigate invoice INV-REVIEW-…"; the action buttons are named exactly "Investigate"
    expect(screen.getAllByRole('button', { name: 'Investigate' })).toHaveLength(2);
  });

  it('shows the empty state when nothing awaits review', async () => {
    stubFetch((url) => (url.includes('decision=REVIEW') ? jsonResponse(200, reviewList(0)) : jsonResponse(404, {})));
    renderWithRouter(<ReviewQueue />);
    expect(await screen.findByText('Review queue is empty')).toBeInTheDocument();
  });
});
