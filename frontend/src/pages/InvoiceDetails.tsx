import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import {
  ArrowLeft,
  FilePdf,
  ArrowSquareOut,
  DownloadSimple,
  Warning,
  CheckCircle,
  XCircle,
  SealCheck,
  Receipt,
} from '@phosphor-icons/react';
import { ApiError, getInvoice, getRun, invoiceDocumentUrl } from '../api';
import type { DecisionResult, InvoiceDetail, LineItemExtracted, RunDetail } from '../types';
import { EmptyState, ErrorState, Skeleton } from '../components/ui/primitives';
import { DecisionBadge, RunStatusBadge, ValidationStatusBadge } from '../components/ui/StatusPill';
import { dateShort, dateTime, money, moneyRaw } from '../utils/formatting';

function Missing() {
  return <span className="field-missing">not extracted</span>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function ConfidenceChip({ value }: { value: unknown }) {
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return <span className="key">confidence n/a</span>;
  const tone = n >= 0.8 ? 'green' : n >= 0.5 ? 'amber' : 'red';
  return <span className={`badge badge-${tone}`} style={{ fontSize: 10 }}>{n.toFixed(2)}</span>;
}

function decisionIcon(decision?: string | null) {
  switch (decision) {
    case 'APPROVE': return <CheckCircle size={20} weight="fill" color="var(--green)" aria-hidden="true" />;
    case 'REJECT': return <XCircle size={20} weight="fill" color="var(--red)" aria-hidden="true" />;
    default: return <Warning size={20} weight="fill" color="var(--amber)" aria-hidden="true" />;
  }
}

function EvidenceList({ evidence }: { evidence: Record<string, unknown> }) {
  const entries = Object.entries(evidence).filter(([, v]) => v && typeof v === 'object');
  if (entries.length === 0) return null;
  return (
    <details style={{ marginTop: 10 }}>
      <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600, color: 'var(--accent)' }}>
        Inspect extraction evidence ({entries.length} fields)
      </summary>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
        {entries.map(([field, value]) => {
          const v = value as { text?: unknown; confidence?: unknown; page?: unknown };
          return (
            <div key={field} className="evidence-block">
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
                <strong style={{ fontSize: 11, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--muted)' }}>{field}</strong>
                <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                  {v.page !== undefined && <span className="mono" style={{ fontSize: 10 }}>p.{String(v.page)}</span>}
                  <ConfidenceChip value={v.confidence} />
                </span>
              </div>
              <div style={{ marginTop: 4 }}>{String(v.text ?? '')}</div>
            </div>
          );
        })}
      </div>
    </details>
  );
}

export default function InvoiceDetails() {
  const { invoiceId = '' } = useParams<{ invoiceId: string }>();
  const invoiceIdNum = Number(invoiceId);
  const navigate = useNavigate();

  const [invoice, setInvoice] = useState<InvoiceDetail | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!Number.isFinite(invoiceIdNum)) {
      setError('That invoice id is not a number.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const inv = await getInvoice(invoiceIdNum);
      setInvoice(inv);
      const latestRun = inv.processing_runs?.[0];
      if (latestRun) {
        try {
          setRun(await getRun(latestRun.run_id));
        } catch (runErr) {
          // The invoice itself loaded — surface the run-level failure softly
          setRun(null);
          setError(runErr instanceof ApiError
            ? `Invoice loaded, but its processing run could not be retrieved (${runErr.message})`
            : 'Invoice loaded, but its processing run could not be retrieved.');
        }
      } else {
        setRun(null);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load this invoice.');
    } finally {
      setLoading(false);
    }
  }, [invoiceIdNum]);

  useEffect(() => {
    load();
  }, [load]);

  const extracted = run?.extraction ?? null;
  const dr: DecisionResult | null | undefined = run?.decision_result;
  const docUrl = Number.isFinite(invoiceIdNum) ? invoiceDocumentUrl(invoiceIdNum) : null;

  const lines: LineItemExtracted[] = useMemo(
    () => extracted?.line_items ?? invoice?.line_items?.map((li) => ({
      description: li.description,
      sku: li.sku,
      quantity: li.quantity,
      unit: li.unit,
      unit_price: li.unit_price,
      line_total: li.line_total,
    })) ?? [],
    [extracted?.line_items, invoice?.line_items],
  );

  if (loading) {
    return (
      <div className="grid grid-12">
        <div className="span-12"><Skeleton style={{ height: 74 }} /></div>
        <div className="span-7"><Skeleton style={{ height: 520 }} /></div>
        <div className="span-5"><Skeleton style={{ height: 420 }} /></div>
      </div>
    );
  }

  if (error && !invoice) {
    return <ErrorState message={error} onRetry={load} />;
  }

  if (!invoice) {
    return <ErrorState message="This invoice does not exist." onRetry={() => navigate('/invoices')} />;
  }

  const vendorName = extracted?.vendor_name ?? invoice.invoice_number ?? null;
  const decision = dr?.decision ?? run?.decision ?? null;

  return (
    <div className="grid grid-12">
      {/* ── Breadcrumb + header strip ─────────────────────────────────────── */}
      <div className="span-12" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <Link to="/invoices" className="card-title-link" style={{ marginBottom: 6 }}>
            <ArrowLeft size={12} weight="bold" aria-hidden="true" /> Invoice history
          </Link>
          <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.02em' }}>
            {invoice.invoice_number ?? <span style={{ color: 'var(--faint)' }}>Unnumbered invoice</span>}
          </h1>
          <div style={{ display: 'flex', gap: 8, marginTop: 6, alignItems: 'center' }}>
            <RunStatusBadge status={run?.status ?? null} />
            <DecisionBadge decision={decision} />
            {extracted?.extraction_status && (
              <span className="mono" style={{ fontSize: 10.5, color: 'var(--faint)' }}>
                extraction {extracted.extraction_status}{extracted.warnings?.length ? ` · ${extracted.warnings.length} warning(s)` : ''}
              </span>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {docUrl && (
            <>
              <a className="btn btn-ghost btn-sm" href={docUrl} target="_blank" rel="noopener noreferrer">
                <ArrowSquareOut size={13} weight="bold" aria-hidden="true" /> Open PDF
              </a>
              <a className="btn btn-ghost btn-sm" href={docUrl} download={`invoice_${invoice.id}.pdf`}>
                <DownloadSimple size={13} weight="bold" aria-hidden="true" /> Download
              </a>
            </>
          )}
        </div>
      </div>

      {error && !run && <div className="span-12"><ErrorState message={error} onRetry={load} /></div>}

      {/* ── Main column ─────────────────────────────────────────────────── */}
      <div className="span-7" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

        {/* A. Overview */}
        <section className="card" aria-labelledby="overview-heading">
          <div className="card-header"><h2 id="overview-heading">Overview</h2></div>
          <dl className="kv">
            <Field label="Vendor">{vendorName ?? <Missing />}</Field>
            <Field label="Vendor tax ID">{extracted?.vendor_tax_id ?? <Missing />}</Field>
            <Field label="Invoice date">{extracted?.invoice_date ? dateShort(extracted.invoice_date) : invoice.invoice_date ? dateShort(invoice.invoice_date) : <Missing />}</Field>
            <Field label="Due date">{extracted?.due_date ? dateShort(extracted.due_date) : invoice.due_date ? dateShort(invoice.due_date) : <Missing />}</Field>
            <Field label="Currency">{extracted?.currency ?? invoice.currency ?? <Missing />}</Field>
            <Field label="PO reference">{extracted?.po_reference ? <code className="key">{extracted.po_reference}</code> : <Missing />}</Field>
            <Field label="Subtotal"><span className="num">{money(extracted?.subtotal ?? invoice.subtotal)}</span></Field>
            <Field label="Tax"><span className="num">{money(extracted?.tax_amount ?? invoice.tax_amount)}</span></Field>
            <Field label="Discount"><span className="num">{money(extracted?.discount_amount ?? invoice.discount_amount)}</span></Field>
            <Field label="Total"><strong className="num">{money(extracted?.total_amount ?? invoice.total_amount)}</strong></Field>
            <Field label="File"><span className="mono" style={{ fontSize: 11 }}>{invoice.original_filename}</span></Field>
            <Field label="Submitted">{dateTime(invoice.created_at)}</Field>
          </dl>
        </section>

        {/* C. Extracted information */}
        <section className="card" aria-labelledby="extract-heading">
          <div className="card-header">
            <div>
              <h2 id="extract-heading">Extracted information</h2>
              <div className="sub">What the document contained, with evidence</div>
            </div>
            {extracted?.evidence && <span className="key">{Object.keys(extracted.evidence).length} evidence rows</span>}
          </div>

          <table className="table lines-table" aria-label="Extracted line items">
            <thead>
              <tr><th>#</th><th>Description</th><th>SKU</th><th className="num">Qty</th><th>Unit</th><th className="num">Unit price</th><th className="num">Line total</th></tr>
            </thead>
            <tbody>
              {lines.length === 0 && <tr><td colSpan={7} style={{ color: 'var(--faint)' }}>No line items extracted.</td></tr>}
              {lines.slice(0, 20).map((li, i) => (
                <tr key={i}>
                  <td className="mono">{i + 1}</td>
                  <td>{li.description ?? <Missing />}</td>
                  <td className="mono">{li.sku ?? '—'}</td>
                  <td className="num">{li.quantity ?? '—'}</td>
                  <td>{li.unit ?? '—'}</td>
                  <td className="num">{moneyRaw(li.unit_price)}</td>
                  <td className="num">{moneyRaw(li.line_total)}</td>
                </tr>
              ))}
              {lines.length > 20 && <tr><td colSpan={7} style={{ color: 'var(--faint)' }}>+ {lines.length - 20} more line(s)</td></tr>}
            </tbody>
          </table>

          {(extracted?.warnings?.length ?? 0) > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 650, letterSpacing: '0.07em', textTransform: 'uppercase', color: 'var(--amber)', marginBottom: 6 }}>
                Extraction warnings ({extracted!.warnings!.length})
              </div>
              <div className="warning-list">
                {extracted!.warnings!.map((w, i) => (
                  <div key={i} className="warning-item"><Warning size={13} weight="fill" aria-hidden="true" style={{ flex: 'none', marginTop: 1 }} /><span>{w}</span></div>
                ))}
              </div>
            </div>
          )}
          {extracted?.evidence && <EvidenceList evidence={extracted.evidence} />}
        </section>

        {/* D. PO comparison */}
        <section className="card" aria-labelledby="po-heading">
          <div className="card-header">
            <div>
              <h2 id="po-heading">Purchase order comparison</h2>
              <div className="sub">Balance outlook at the time of processing</div>
            </div>
            <ValidationStatusBadge status={run?.amount_validation?.status} />
          </div>
          <dl className="kv">
            <Field label="Matched PO">{run?.po_match?.matched_po?.po_number ? <code className="key">{run.po_match.matched_po.po_number}</code> : <Missing />}</Field>
            <Field label="PO total"><span className="num">{money(run?.amount_validation?.po_total)}</span></Field>
            <Field label="Invoice amount"><span className="num">{money(run?.amount_validation?.invoice_amount)}</span></Field>
            <Field label="Previously approved invoiced"><span className="num">{money(run?.amount_validation?.previously_approved_invoiced)}</span></Field>
            <Field label="Remaining PO balance"><span className="num"><strong>{money(run?.amount_validation?.remaining_po_balance)}</strong></span></Field>
            <Field label="Balance basis">
              {run?.amount_validation?.metadata?.provisional ? (
                <span className="badge badge-amber" title="No APPROVE history yet — balance derived from unapproved invoices">PROVISIONAL</span>
              ) : (
                <span className="badge badge-slate">COMMITTED (approved history)</span>
              )}
            </Field>
          </dl>
          {run?.line_item_validation && (
            <div className="evidence-block" style={{ marginTop: 10 }}>
              <strong style={{ fontSize: 11.5 }}>Line items:</strong> {run.line_item_validation.explanation ?? '—'}
              {(run.line_item_validation.matched_items?.length ?? 0) > 0 && (
                <span className="mono" style={{ display: 'block', marginTop: 4, fontSize: 10.5 }}>
                  {run.line_item_validation.matched_items!.length} matched · {run.line_item_validation.unmatched_invoice_items?.length ?? 0} extra invoice · {run.line_item_validation.unmatched_po_items?.length ?? 0} unmatched PO
                </span>
              )}
            </div>
          )}
        </section>

        {/* E. Validation results */}
        <section className="card" aria-labelledby="validations-heading">
          <div className="card-header"><h2 id="validations-heading">Validation results</h2></div>
          <div className="validation-grid">
            {[
              { title: 'Vendor match', result: run?.vendor_match },
              { title: 'PO match', result: run?.po_match },
              { title: 'Duplicate detection', result: run?.duplicate_check },
              { title: 'Amount vs PO balance', result: run?.amount_validation },
              { title: 'Line items', result: run?.line_item_validation },
              { title: 'Tax arithmetic', result: run?.tax_validation },
            ].map(({ title, result }) => (
              <div className="validation-card" key={title}>
                <h3>{title}</h3>
                <div><ValidationStatusBadge status={result?.status} /></div>
                <p>{result?.explanation ?? 'This check was not run.'}</p>
                {result?.evidence && Object.keys(result.evidence).length > 0 && (
                  <div className="mono">{Object.entries(result.evidence).slice(0, 3).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(' · ')}</div>
                )}
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* ── Right column: decision + document ───────────────────────────── */}
      <div className="span-5" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

        {/* F. Final decision */}
        <section className="card" aria-labelledby="decision-heading">
          <div className="card-header" style={{ marginBottom: 8 }}>
            <div>
              <h2 id="decision-heading">Final decision</h2>
              <div className="sub">Policy v{dr?.policy_version ?? '1.0'} · deterministic rules, no LLM judgement</div>
            </div>
            {run?.status && <RunStatusBadge status={run.status} />}
          </div>

          <div className={`decision-banner ${decision ?? 'FAILED'}`}>
            <span aria-hidden="true" style={{ marginTop: 2 }}>{decisionIcon(decision)}</span>
            <div>
              <div className="db-title">{decision ?? 'Not decided'}</div>
              <div className="db-sub">{dr?.summary ?? run?.error_message ?? 'No decision recorded — run may still be in-flight or failed technically.'}</div>
            </div>
          </div>

          {dr && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 650, letterSpacing: '0.07em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 6 }}>
                Rules evaluated — {dr.rules_evaluated.length}
              </div>
              <div>
                {dr.rules_evaluated.map((rule, i) => (
                  <div className="rule-row" key={i}>
                    <span className="rule-id" title={rule.rule_name}>{rule.rule_id}</span>
                    <span className={rule.severity === 'REJECT' ? 'rule-fail' : rule.status === 'WARNING' ? undefined : 'rule-pass'}
                          style={rule.status === 'WARNING' && rule.severity !== 'REJECT' ? { color: 'var(--amber)' } : undefined}>
                      {rule.explanation}
                    </span>
                  </div>
                ))}
              </div>
              {dr.hard_failures.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--red)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 4 }}>Hard failures</div>
                  {dr.hard_failures.map((f, i) => <div key={i} className="warning-item" style={{ background: 'var(--red-tint)', borderColor: 'var(--red-border)', color: 'var(--red)' }}><XCircle size={13} weight="fill" aria-hidden="true" style={{ flex: 'none', marginTop: 1 }} /><span>{f}</span></div>)}
                </div>
              )}
              {dr.review_reasons.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--amber)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 4 }}>Reasons for review</div>
                  {dr.review_reasons.map((f, i) => <div key={i} className="warning-item"><Warning size={13} weight="fill" aria-hidden="true" style={{ flex: 'none', marginTop: 1 }} /><span>{f}</span></div>)}
                </div>
              )}
            </div>
          )}
        </section>

        {/* B. Document preview */}
        <section className="card" aria-labelledby="doc-heading">
          <div className="card-header">
            <div>
              <h2 id="doc-heading"><FilePdf size={16} weight="duotone" aria-hidden="true" style={{ verticalAlign: '-3px', marginRight: 8 }} />Document</h2>
              <div className="sub">Stored under a server-generated name — the upload filename is metadata only</div>
            </div>
          </div>
          {docUrl ? (
            <iframe className="doc-frame" src={docUrl} title={`PDF preview of invoice ${invoice.invoice_number ?? invoice.id}`} />
          ) : (
            <EmptyState title="No stored document" sub="This invoice has no storage path recorded." />
          )}
          {invoice.file_sha256 && <p className="mono" style={{ fontSize: 10, color: 'var(--faint)', marginTop: 8, overflowWrap: 'anywhere' }} title="SHA-256 of the stored file">sha256 {invoice.file_sha256}</p>}
        </section>
      </div>

      {/* ── G. Audit history ─────────────────────────────────────────────── */}
      <section className="card span-12" aria-labelledby="audit-heading">
        <div className="card-header">
          <div>
            <h2 id="audit-heading"><SealCheck size={16} weight="duotone" aria-hidden="true" style={{ verticalAlign: '-3px', marginRight: 8 }} />Audit history</h2>
            <div className="sub">Every stage event persisted for this run, chronological — nothing inferred after the fact</div>
          </div>
          <Link to={run?.run_id ? `/processing/${run.run_id}` : '#'} className="card-title-link">Live view <ArrowSquareOut size={12} weight="bold" aria-hidden="true" /></Link>
        </div>
        <ol className="timeline" style={{ marginTop: -4 }}>
          {(run?.events ?? []).map((event) => (
            <li key={event.id} className={`timeline-item ${event.status === 'COMPLETED' ? 'done' : ''}`}>
              <span className={`timeline-dot dot-${event.status === 'RUNNING' ? 'running' : event.status === 'FAILED' ? 'failed' : event.status === 'COMPLETED' ? 'completed' : event.status === 'WARNING' ? 'warning' : 'skipped'}`} aria-hidden="true">
                <Receipt size={11} weight="bold" />
              </span>
              <div className="timeline-body">
                <div className="timeline-head">
                  <span className="timeline-stage">{event.stage.replace(/_/g, ' ')}</span>
                  <span className="timeline-time">{dateTime(event.created_at)}</span>
                  <span className="badge badge-slate" style={{ fontSize: 9 }}>{event.status}</span>
                </div>
                <p className="timeline-msg">{event.message ?? '—'}</p>
              </div>
            </li>
          ))}
          {(run?.events ?? []).length === 0 && <li style={{ color: 'var(--faint)', fontSize: 12.5, padding: 12 }}>Events unavailable — the run could not be loaded.</li>}
        </ol>
      </section>
    </div>
  );
}
