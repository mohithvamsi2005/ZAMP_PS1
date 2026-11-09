import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FileText,
  UploadSimple,
  X,
  ShieldCheck,
  CheckCircle,
  WarningOctagon,
} from '@phosphor-icons/react';
import { uploadInvoiceWithProgress } from '../api';
import { fileSize } from '../utils/formatting';
import { SmallSpinner } from '../components/ui/primitives';

type Phase = 'idle' | 'selected' | 'uploading' | 'error';

const MAX_MB = 20;

export default function UploadInvoice() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [progress, setProgress] = useState(0);
  const [dragActive, setDragActive] = useState(false);

  const validate = useCallback((f: File): string | null => {
    if (f.size === 0) return 'This file is empty.';
    if (f.size > MAX_MB * 1024 * 1024) return `Files must be ${MAX_MB} MB or smaller (this one is ${fileSize(f.size)}).`;
    if (!f.name.toLowerCase().endsWith('.pdf')) return 'Only PDF files can be uploaded.';
    return null;
  }, []);

  const selectFile = useCallback((f: File | null) => {
    if (!f) return;
    const problem = validate(f);
    if (problem) {
      setFile(null);
      setPhase('error');
      setError(problem);
      return;
    }
    setFile(f);
    setError(null);
    setPhase('selected');
    setProgress(0);
  }, [validate]);

  const clearSelection = useCallback(() => {
    abortRef.current?.abort();
    setFile(null);
    setError(null);
    setPhase('idle');
    setProgress(0);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, []);

  const onDrop = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragActive(false);
    selectFile(event.dataTransfer.files?.[0] ?? null);
  }, [selectFile]);

  // Kill any in-flight upload when navigating away
  useEffect(() => () => abortRef.current?.abort(), []);

  const submit = useCallback(async () => {
    if (!file || phase === 'uploading') return;
    setPhase('uploading');
    setProgress(0);
    setError(null);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const outcome = await uploadInvoiceWithProgress(file, setProgress, controller.signal);
      setPhase('idle');
      navigate(`/processing/${outcome.runId}`);
    } catch (err) {
      setPhase('error');
      setError(err instanceof Error ? err.message : 'Upload failed.');
    } finally {
      abortRef.current = null;
    }
  }, [file, phase, navigate]);

  const uploading = phase === 'uploading';

  return (
    <div className="grid grid-12">
      <div className="span-7" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div className="card">
          <div className="card-header">
            <div>
              <h2>Invoice document</h2>
              <div className="sub">PDF only · max {MAX_MB} MB · scanned and digital both supported</div>
            </div>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf,.pdf"
            className="sr-only"
            aria-label="PDF invoice file"
            onChange={(e) => selectFile(e.target.files?.[0] ?? null)}
          />

          {phase !== 'selected' && (
            <div
              className={`dropzone${dragActive ? ' drag-active' : ''}${phase === 'error' ? ' has-error' : ''}`}
              role="button"
              tabIndex={0}
              aria-label="Drop a PDF invoice here, or activate to browse files"
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click(); }}
              onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
              onDragLeave={() => setDragActive(false)}
              onDrop={onDrop}
            >
              <UploadSimple size={30} weight="duotone" className="dropzone-glyph" aria-hidden="true" />
              <div className="dropzone-title">Drop your invoice PDF here</div>
              <p className="dropzone-sub">or browse from your computer — the file never leaves this server's storage after upload</p>
            </div>
          )}

          {phase === 'selected' && file && (
            <div className="file-card" role="status">
              <FileText size={26} weight="duotone" color="var(--accent)" aria-hidden="true" style={{ flex: 'none' }} />
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontWeight: 620, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={file.name}>{file.name}</div>
                <div className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>{fileSize(file.size)} · PDF document</div>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={clearSelection} aria-label="Remove selected file">
                <X size={14} weight="bold" aria-hidden="true" /> Remove
              </button>
            </div>
          )}

          {error && (
            <div className="error-box" style={{ marginTop: 12 }} role="alert">
              <WarningOctagon size={16} weight="fill" aria-hidden="true" style={{ flex: 'none', marginTop: 2 }} />
              <span>{error}</span>
            </div>
          )}

          {uploading && (
            <div style={{ marginTop: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}><SmallSpinner /> Uploading…</span>
                <span className="mono num">{Math.round(progress * 100)}%</span>
              </div>
              <div className="progress-track" role="progressbar" aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100} aria-label="Upload progress">
                <div className="progress-bar" style={{ width: `${progress * 100}%` }} />
              </div>
            </div>
          )}

          <div style={{ display: 'flex', gap: 10, marginTop: 14, alignItems: 'center' }}>
            <button
              className="btn btn-primary"
              disabled={phase !== 'selected'}
              onClick={submit}
              aria-busy={uploading}
            >
              {uploading ? <><SmallSpinner /> Sending…</> : <><UploadSimple size={15} weight="bold" aria-hidden="true" /> Upload and process</>}
            </button>
            {file && !uploading && (
              <button className="btn btn-ghost" onClick={clearSelection}>Cancel</button>
            )}
            {uploading && (
              <button className="btn btn-ghost" onClick={clearSelection}>Cancel upload</button>
            )}
          </div>
        </div>

        <div className="card" style={{ background: 'var(--surface-raised)' }}>
          <div className="card-header" style={{ marginBottom: 6 }}>
            <h2 style={{ fontSize: 13 }}>What happens after you click Upload</h2>
          </div>
          <ol className="upload-steps">
            <li><ShieldCheck size={13} weight="fill" aria-hidden="true" /> The backend validates the file (magic bytes, size), stores it under a generated name, and queues a processing run — you get a <code className="mono">202 Accepted</code> with a run ID.</li>
            <li><FileText size={13} weight="fill" aria-hidden="true" /> Background workers extract text (OCR when pages are images), then an LLM extracts structured invoice data with per-field evidence.</li>
            <li>Matching, duplicate checks and three validations run against your procurement database, then the deterministic decision engine returns APPROVE, REVIEW or REJECT — followed by full audit persistence you can inspect on the run page.</li>
          </ol>
        </div>
      </div>

      <div className="span-5" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div className="card">
          <div className="card-header" style={{ marginBottom: 6 }}>
            <h2 style={{ fontSize: 13 }}>Acceptable content</h2>
          </div>
          <ul className="accept-list">
            <li>Invoice PDFs with text layer or scanned images (OCR fallback)</li>
            <li>Indian and international vendor layouts — extraction is schema-first, layout-agnostic</li>
            <li>Files with line-item tables; missing fields are flagged, never guessed</li>
          </ul>
        </div>

        <div className="card">
          <div className="card-header" style={{ marginBottom: 6 }}>
            <h2 style={{ fontSize: 13 }}>Not accepted</h2>
          </div>
          <ul className="accept-list">
            <li>Non-PDF files, renamed executables or HTML</li>
            <li>Empty files or larger than {MAX_MB} MB</li>
            <li>Documents you cannot legally process — screening logic left to you</li>
          </ul>
        </div>

        <div className="card" style={{ borderColor: '#cfe3da' }}>
          <div className="card-header" style={{ marginBottom: 6 }}>
            <h2 style={{ fontSize: 13, color: 'var(--accent-strong)' }}><CheckCircle size={13} weight="bold" aria-hidden="true" style={{ verticalAlign: '-2px', marginRight: 6 }} />Guarantees</h2>
          </div>
          <ul className="accept-list">
            <li>Your filename is stored as display metadata only, never as a file path</li>
            <li>Processing outcomes are deterministic given the same inputs and policy version</li>
            <li>Every stage's result is persisted and shown verbatim — nothing hidden from the audit trail</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
