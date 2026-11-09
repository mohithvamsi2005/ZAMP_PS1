/** TypeScript contracts mirroring the ACTUAL backend payloads (Phase 3–7).
 *  Field names match app/services/run_store.py + app/api/*.py response models. */

export type RunStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';
export type Decision = 'APPROVE' | 'REVIEW' | 'REJECT';
export type EventStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'WARNING' | 'FAILED' | 'SKIPPED';
export type StatusTone = 'green' | 'amber' | 'red' | 'slate' | 'accent';

// ── Upload / invoice ───────────────────────────────────────────────────────

export interface UploadResponse {
  invoice_id: number;
  run_id: string;
  status: string;
  message: string;
}

export interface InvoiceLineOut {
  id: number;
  description: string;
  sku?: string | null;
  quantity?: string | null;
  unit?: string | null;
  unit_price?: string | null;
  line_total?: string | null;
}

export interface RunBrief {
  run_id: string;
  status: RunStatus;
  decision?: Decision | null;
  created_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
}

export interface InvoiceDetail {
  id: number;
  invoice_number?: string | null;
  vendor_id?: number | null;
  purchase_order_id?: number | null;
  invoice_date?: string | null;
  due_date?: string | null;
  currency?: string | null;
  subtotal?: string | null;
  tax_amount?: string | null;
  discount_amount?: string | null;
  total_amount?: string | null;
  original_filename?: string | null;
  file_sha256?: string | null;
  created_at?: string | null;
  line_items: InvoiceLineOut[];
  processing_runs: RunBrief[];
}

// ── Phase 7 invoice history list (GET /api/invoices) ───────────────────────

export interface InvoiceListItem {
  id: number;
  invoice_number?: string | null;
  vendor_name?: string | null;
  po_reference?: string | null;
  total_amount?: string | null;
  currency?: string | null;
  original_filename?: string | null;
  file_sha256?: string | null;
  created_at?: string | null;
  last_run_id?: string | null;
  last_run_status?: RunStatus | null;
  last_run_decision?: Decision | null;
}

export interface InvoiceListResponse {
  total: number;
  page: number;
  page_size: number;
  invoices: InvoiceListItem[];
}

export interface InvoiceListParams {
  search?: string;
  decision?: Decision;
  status?: RunStatus;
  sort_by?: 'submission' | 'total_amount';
  sort_dir?: 'asc' | 'desc';
  page?: number;
  page_size?: number;
}

// ── Runs ────────────────────────────────────────────────────────────────────

export interface RunSummary {
  run_id: string;
  invoice_id?: number | null;
  status: RunStatus;
  decision?: Decision | null;
  llm_provider?: string | null;
  llm_model?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
}

export interface RunsListResponse {
  total: number;
  page: number;
  page_size: number;
  runs: RunSummary[];
}

export interface RunEvent {
  id: number;
  stage: string;
  status: EventStatus;
  message?: string | null;
  details: Record<string, unknown>;
  created_at?: string | null;
}

export interface LineItemExtracted {
  description?: string | null;
  sku?: string | null;
  quantity?: string | null;
  unit?: string | null;
  unit_price?: string | null;
  line_total?: string | null;
}

export interface ExtractionEnvelope {
  invoice_number?: string | null;
  invoice_date?: string | null;
  due_date?: string | null;
  currency?: string | null;
  po_reference?: string | null;
  vendor_name?: string | null;
  vendor_tax_id?: string | null;
  subtotal?: string | null;
  tax_amount?: string | null;
  discount_amount?: string | null;
  total_amount?: string | null;
  line_items?: LineItemExtracted[];
  source_pages?: number[];
  evidence?: Record<string, unknown>;
  extraction_status?: 'SUCCESS' | 'PARTIAL' | 'FAILED';
  warnings?: string[];
}

export interface ValidationResult {
  check_name?: string;
  status: 'PASS' | 'FAIL' | 'WARNING' | 'UNKNOWN' | string;
  explanation?: string;
  evidence?: Record<string, unknown> | null;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface VendorMatch extends ValidationResult {
  matched_vendor?: { id: number; vendor_code: string; legal_name: string } | null;
  candidates?: Array<Record<string, unknown>>;
}

export interface PoMatch extends ValidationResult {
  matched_po?: { id: number; po_number: string; [k: string]: unknown } | null;
  candidates?: Array<Record<string, unknown>>;
}

export interface AmountValidation extends ValidationResult {
  invoice_amount?: string;
  po_total?: string | null;
  remaining_po_balance?: string | null;
  previously_approved_invoiced?: string | null;
  difference?: string | null;
  tolerance_absolute?: string | null;
  tolerance_percent?: number | null;
}

export interface LineItemValidation extends ValidationResult {
  matched_items?: Array<Record<string, unknown>>;
  unmatched_invoice_items?: Array<Record<string, unknown>>;
  unmatched_po_items?: Array<Record<string, unknown>>;
}

export interface TaxValidation extends ValidationResult {
  subtotal?: string | null;
  tax_amount?: string | null;
  discount_amount?: string | null;
  expected_total?: string | null;
  actual_total?: string | null;
  difference?: string | null;
}

export interface DecisionRule {
  rule_id: string;
  rule_name: string;
  status: string;
  severity: string;
  explanation: string;
  evidence?: Record<string, unknown>;
}

export interface DecisionResult {
  decision: Decision;
  policy_version: string;
  summary: string;
  rules_evaluated: DecisionRule[];
  hard_failures: string[];
  review_reasons: string[];
  approval_eligible: boolean;
}

export interface RunDetail extends RunSummary {
  extraction?: ExtractionEnvelope | null;
  document_meta?: Record<string, unknown> | null;
  vendor_match?: VendorMatch | null;
  po_match?: PoMatch | null;
  duplicate_check?: ValidationResult | null;
  amount_validation?: AmountValidation | null;
  line_item_validation?: LineItemValidation | null;
  tax_validation?: TaxValidation | null;
  decision_result?: DecisionResult | null;
  invoice?: InvoiceDetail | null;
  events: RunEvent[];
}

// ── Dashboard (Phase 7) ──────────────────────────────────────────────────────

export interface DashboardTotals {
  invoices: number;
  runs: number;
  completed_runs: number;
  failed_runs: number;
  pending_runs: number;
  running_runs: number;
}

export interface RecentRun {
  run_id: string;
  invoice_id?: number | null;
  invoice_number?: string | null;
  vendor_name?: string | null;
  po_reference?: string | null;
  total_amount?: string | null;
  currency?: string | null;
  original_filename?: string | null;
  status?: RunStatus | null;
  decision?: Decision | null;
  error_message?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  duration_seconds?: number | null;
}

export interface DashboardSummary {
  totals: DashboardTotals;
  decisions: { APPROVE: number; REVIEW: number; REJECT: number };
  decision_total: number;
  approval_rate: number | null;
  review_queue: number;
  avg_processing_seconds: number | null;
  activity_last_14_days: Array<{ date: string; submitted: number }>;
  recent_runs: RecentRun[];
  latest_failed_runs: RecentRun[];
}

// ── Health ───────────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: string;
  service: string;
  database: string;
  llm_provider: string;
  llm_model: string;
}
