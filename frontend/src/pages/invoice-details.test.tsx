import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { Routes, Route, MemoryRouter } from 'react-router-dom';
import { render } from '@testing-library/react';
import { stubFetch, jsonResponse } from '../test/helpers';
import { fixtureRunDetail } from '../test/fixtures';
import InvoiceDetails from './InvoiceDetails';

function renderAt(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/invoices/${id}`]}>
      <Routes>
        <Route path="/invoices/:invoiceId" element={<InvoiceDetails />} />
      </Routes>
    </MemoryRouter>,
  );
}

const detailResponse = () => {
  const d = fixtureRunDetail();
  return {
    invoice: d.invoice,
    run: d,
  };
};

describe('Invoice detail page', () => {
  it('renders overview, extraction, validations, decision and audit sections from the real payloads', async () => {
    stubFetch((url) => {
      if (url.endsWith('/api/invoices/42')) return jsonResponse(200, detailResponse().invoice);
      if (url.endsWith('/api/runs/run-fixture-0001')) return jsonResponse(200, fixtureRunDetail());
      return jsonResponse(404, {});
    });
    renderAt('42');

    // A. Overview — vendor, total, status, decision
    expect(await screen.findByText('INV-DEMO-1001')).toBeInTheDocument();
    expect(screen.getAllByText('ABC Industrial Supplies Pvt Ltd').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/₹60,000.00/).length).toBeGreaterThan(0);
    expect(screen.getAllByText('REVIEW').length).toBeGreaterThan(0);

    // C. Extracted information — line items rendered
    expect(screen.getByText('Welding electrodes 3.2mm')).toBeInTheDocument();
    expect(screen.getByText('Safety goggles, anti-fog')).toBeInTheDocument();
    expect(screen.getByText('Extraction warnings (1)')).toBeInTheDocument();

    // E. Validations — all six checks visible
    expect(screen.getByText('Vendor match')).toBeInTheDocument();
    expect(screen.getByText('PO match')).toBeInTheDocument();
    expect(screen.getByText('Duplicate detection')).toBeInTheDocument();
    expect(screen.getByText('Amount vs PO balance')).toBeInTheDocument();
    expect(screen.getByText('Line items')).toBeInTheDocument();
    expect(screen.getByText('Tax arithmetic')).toBeInTheDocument();

    // F. Final decision — policy reference and rule evaluation visible
    expect(screen.getByText('EXTRACTION_001')).toBeInTheDocument();

    // G. Audit history — persisted events listed
    expect(screen.getByText('Audit history')).toBeInTheDocument();
  });

  it('shows a 404 error state for an unknown invoice id', async () => {
    stubFetch(() => jsonResponse(404, { detail: 'Invoice 999 not found' }));
    renderAt('999');
    expect(await screen.findByRole('alert')).toHaveTextContent(/not found/i);
  });

  it('renders a not-extracted placeholder instead of inventing values', async () => {
    const bare = fixtureRunDetail({
      extraction: { invoice_number: 'INV-X', po_reference: null, vendor_name: null, vendor_tax_id: null, line_items: [], evidence: {}, extraction_status: 'PARTIAL', warnings: ['mostly blank'] },
      vendor_match: null,
    });
    const inv = { ...bare.invoice, invoice_number: 'INV-X' };
    stubFetch((url) => {
      if (url.endsWith('/api/invoices/43')) return jsonResponse(200, inv);
      if (url.endsWith('/api/runs/run-fixture-0001')) return jsonResponse(200, bare);
      return jsonResponse(404, {});
    });
    renderAt('43');
    expect((await screen.findAllByText('not extracted')).length).toBeGreaterThan(2);
  });
});
