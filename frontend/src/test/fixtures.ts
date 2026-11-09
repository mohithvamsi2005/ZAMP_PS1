import type { DashboardSummary, RunDetail, RunEvent, RunsListResponse } from '../types';

export const FIXTURE_NOW = '2026-11-09T16:09:38.338493+00:00';
export const FIXTURE_STARTED = '2026-11-09T16:09:38.338493+00:00';
export const FIXTURE_COMPLETED = '2026-11-09T16:10:30.354546+00:00';

export function fixtureEvents(count = 24): RunEvent[] {
  const stages = [
    'RECEIVED', 'RECEIVED', 'DOCUMENT_PROCESSING', 'DOCUMENT_PROCESSING',
    'OCR_PROCESSING', 'LLM_EXTRACTION', 'LLM_EXTRACTION',
    'VENDOR_MATCHING', 'VENDOR_MATCHING', 'PO_MATCHING', 'PO_MATCHING',
    'DUPLICATE_CHECK', 'DUPLICATE_CHECK', 'AMOUNT_VALIDATION', 'AMOUNT_VALIDATION',
    'LINE_ITEM_VALIDATION', 'LINE_ITEM_VALIDATION', 'TAX_VALIDATION', 'TAX_VALIDATION',
    'DECISION', 'DECISION', 'PERSISTENCE', 'PERSISTENCE', 'COMPLETED',
  ];
  const all = stages.map((stage, i) => ({
    id: 100 + i,
    stage,
    status: (i % 3 === 0 || stage === 'OCR_PROCESSING' ? 'SKIPPED' : i % 3 === 2 ? 'RUNNING' : 'COMPLETED') as RunEvent['status'],
    message: `Fixture event for ${stage} (#${i + 1})`,
    details: {},
    created_at: new Date(Date.parse(FIXTURE_NOW) + i * 1000).toISOString(),
  }));
  return all.slice(0, count);
}

export function fixtureRunDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    run_id: 'run-fixture-0001',
    invoice_id: 42,
    status: 'COMPLETED',
    decision: 'REVIEW',
    llm_provider: 'openrouter',
    llm_model: 'nvidia/nemotron-3-ultra-550b-a55b:free',
    started_at: FIXTURE_STARTED,
    completed_at: FIXTURE_COMPLETED,
    error_message: null,
    created_at: FIXTURE_NOW,
    extraction: {
      invoice_number: 'INV-DEMO-1001',
      invoice_date: '2026-11-05',
      due_date: '2026-12-05',
      currency: 'INR',
      po_reference: 'PO-2044',
      vendor_name: 'ABC Industrial Supplies Pvt Ltd',
      vendor_tax_id: null,
      subtotal: '60000.00',
      tax_amount: '0.00',
      discount_amount: '0.00',
      total_amount: '60000.00',
      line_items: [
        { description: 'Welding electrodes 3.2mm', sku: 'ELEC-3.2', quantity: '200.0000', unit: 'kg', unit_price: '250.00', line_total: '50000.00' },
        { description: 'Safety goggles, anti-fog', sku: 'GOGGLE-AF', quantity: '100.0000', unit: 'pcs', unit_price: '100.00', line_total: '10000.00' },
      ],
      source_pages: [1],
      evidence: {
        invoice_number: { text: 'Invoice: INV-DEMO-1001', page: 1, confidence: 0.98 },
        vendor_name: { text: 'ABC Industrial Supplies Pvt Ltd', page: 1, confidence: 0.96 },
        total_amount: { text: 'Total: 60000.00', page: 1, confidence: 0.97 },
      },
      extraction_status: 'SUCCESS',
      warnings: ['Vendor tax ID not present in document'],
    },
    document_meta: { page_count: 1, pages_processed: [{ page: 1, method: 'PDF_TEXT', confidence: 1.0 }] },
    vendor_match: {
      check_name: 'Vendor match',
      status: 'MATCHED',
      match_method: 'EXACT_NAME',
      confidence: 1.0,
      matched_vendor: { id: 1, vendor_code: 'V-001', legal_name: 'ABC Industrial Supplies Pvt Ltd' },
      explanation: 'Normalized name matches vendor V-001',
      evidence: null,
    },
    po_match: {
      check_name: 'PO match',
      status: 'MATCHED',
      match_method: 'EXACT_PO_NUMBER',
      matched_po: { id: 4, po_number: 'PO-2044', vendor_id: 1, total_amount: '60000.00', currency: 'INR', status: 'OPEN' },
      explanation: 'Exact PO number PO-2044 matches PO-2044',
      evidence: null,
    },
    duplicate_check: {
      check_name: 'Duplicate detection',
      status: 'NO_DUPLICATE_FOUND',
      explanation: 'No duplicates found',
      evidence: { excluded_invoice_id: 42 },
    },
    amount_validation: {
      check_name: 'Amount validation',
      status: 'PASS',
      invoice_amount: '60000.00',
      po_total: '60000.00',
      remaining_po_balance: '0.00',
      previously_approved_invoiced: '0.00',
      tolerance_absolute: '100.00',
      tolerance_percent: 1.0,
      explanation: 'Invoice 60000.00 within remaining PO balance. PO total=60000.00, previously approved=0, remaining after=0.00',
      metadata: { provisional: false },
      evidence: null,
    },
    line_item_validation: {
      check_name: 'Line-item validation',
      status: 'PASS',
      matched_items: [{ invoice_line_index: 0, po_line_index: 0, status: 'MATCHED' }],
      unmatched_invoice_items: [],
      unmatched_po_items: [],
      explanation: 'All 2 line items match',
      evidence: null,
    },
    tax_validation: {
      check_name: 'Tax arithmetic',
      status: 'PASS',
      subtotal: '60000.00',
      tax_amount: '0.00',
      discount_amount: '0.00',
      expected_total: '60000.00',
      actual_total: '60000.00',
      difference: '0.00',
      explanation: '60000.00 + 0.00 − 0 = 60000.00',
      evidence: null,
    },
    decision_result: {
      decision: 'REVIEW',
      policy_version: '1.0',
      summary: 'Invoice requires human verification.',
      rules_evaluated: [
        { rule_id: 'EXTRACTION_001', rule_name: 'Extraction evidence quality', status: 'WARNING', severity: 'REVIEW', explanation: 'Extraction evidence is insufficient for automatic approval: Extraction warnings: Vendor tax ID not present in document.' },
      ],
      hard_failures: [],
      review_reasons: ['Extraction evidence is insufficient for automatic approval: Extraction warnings: Vendor tax ID not present in document. Human must verify the source document.'],
      approval_eligible: false,
    },
    invoice: {
      id: 42,
      invoice_number: 'INV-DEMO-1001',
      vendor_id: 1,
      purchase_order_id: 4,
      invoice_date: FIXTURE_NOW,
      due_date: null,
      currency: 'INR',
      subtotal: '60000.00',
      tax_amount: '0.00',
      discount_amount: '0.00',
      total_amount: '60000.00',
      original_filename: 'demo_approve.pdf',
      file_sha256: '8477ef4c4287d4e7ea4bc7070c9936c88216a410b9528cfb3ac53801e17769c1',
      created_at: FIXTURE_NOW,
      line_items: [
        { id: 101, description: 'Welding electrodes 3.2mm', sku: 'ELEC-3.2', quantity: '200.0000', unit: 'kg', unit_price: '250.00', line_total: '50000.00' },
        { id: 102, description: 'Safety goggles, anti-fog', sku: 'GOGGLE-AF', quantity: '100.0000', unit: 'pcs', unit_price: '100.00', line_total: '10000.00' },
      ],
      processing_runs: [{ run_id: 'run-fixture-0001', status: 'COMPLETED', decision: 'REVIEW', created_at: FIXTURE_STARTED, completed_at: FIXTURE_COMPLETED, error_message: null }],
    },
    events: fixtureEvents(24),
    ...overrides,
  } as RunDetail;
}

export function fixtureDashboard(): DashboardSummary {
  const now = Date.now();
  return {
    totals: { invoices: 8, runs: 5, completed_runs: 4, failed_runs: 1, pending_runs: 0, running_runs: 0 },
    decisions: { APPROVE: 1, REVIEW: 2, REJECT: 1 },
    decision_total: 4,
    approval_rate: 25,
    review_queue: 2,
    avg_processing_seconds: 187.3,
    activity_last_14_days: Array.from({ length: 14 }, (_, i) => ({
      date: new Date(now - (13 - i) * 86_400_000).toISOString().slice(0, 10),
      submitted: i % 5 === 3 ? 1 : 0,
    })),
    recent_runs: [
      {
        run_id: 'run-fixture-0001', invoice_id: 42, invoice_number: 'INV-DEMO-1001',
        vendor_name: 'ABC Industrial Supplies Pvt Ltd', po_reference: 'PO-2044',
        total_amount: '60000.00', currency: 'INR', original_filename: 'demo_approve.pdf',
        status: 'COMPLETED', decision: 'REVIEW', error_message: null,
        created_at: FIXTURE_NOW, started_at: FIXTURE_STARTED, completed_at: FIXTURE_COMPLETED,
        duration_seconds: 52.0,
      },
    ],
    latest_failed_runs: [
      {
        run_id: 'run-fixture-failed-1', invoice_id: 44, invoice_number: 'INV-DEMO-1002',
        vendor_name: 'Sharma Electrical Components', po_reference: 'PO-2047',
        total_amount: '30000.00', currency: 'INR', original_filename: 'demo_blocked.pdf',
        status: 'FAILED', decision: null,
        error_message: 'LLM extraction failed: rate limit exceeded after 2 attempts',
        created_at: FIXTURE_STARTED, started_at: FIXTURE_STARTED, completed_at: null,
        duration_seconds: 4.2,
      },
    ],
  };
}

export function fixtureRunsList(): RunsListResponse {
  return {
    total: 2,
    page: 1,
    page_size: 20,
    runs: [
      { run_id: 'run-fixture-0001', invoice_id: 42, status: 'COMPLETED', decision: 'REVIEW', llm_provider: 'openrouter', llm_model: 'x', created_at: FIXTURE_NOW, started_at: FIXTURE_STARTED, completed_at: FIXTURE_COMPLETED, error_message: null },
      { run_id: 'run-fixture-failed-1', invoice_id: 44, status: 'FAILED', decision: null, llm_provider: null, llm_model: null, created_at: FIXTURE_STARTED, started_at: FIXTURE_STARTED, completed_at: null, error_message: 'LLM extraction failed' },
    ],
  };
}
