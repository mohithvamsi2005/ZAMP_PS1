import { apiGet, apiPost, apiUrl } from './client';
import type {
  DashboardSummary,
  InvoiceDetail,
  InvoiceListParams,
  InvoiceListResponse,
  ResetResponse,
} from '../types';

export interface UploadOutcome {
  invoiceId: number;
  runId: string;
}

const MAX_UPLOAD_BYTES = 20 * 1024 * 1024; // mirrors backend MAX_UPLOAD_MB=20

export function uploadInvoiceWithProgress(
  file: File,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<UploadOutcome> {
  if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
    return Promise.reject(new Error('Only PDF files can be uploaded.'));
  }
  if (file.size === 0) {
    return Promise.reject(new Error('The selected file is empty.'));
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return Promise.reject(new Error('Files must be 20 MB or smaller.'));
  }

  return new Promise<UploadOutcome>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', apiUrl('/invoices/upload'));

    const onAbort = () => xhr.abort();
    signal?.addEventListener('abort', onAbort, { once: true });

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      signal?.removeEventListener('abort', onAbort);
      if (xhr.status === 202) {
        try {
          const body = JSON.parse(xhr.responseText) as { invoice_id: number; run_id: string };
          resolve({ invoiceId: body.invoice_id, runId: body.run_id });
        } catch {
          reject(new Error('The server returned an unreadable upload response.'));
        }
        return;
      }
      let detail = 'Upload failed.';
      try {
        const body = JSON.parse(xhr.responseText) as { detail?: unknown };
        detail = typeof body.detail === 'string' ? body.detail
          : Array.isArray(body.detail) ? body.detail.map((d) => (d as { msg?: string }).msg ?? String(d)).join('; ')
          : detail;
      } catch {
        /* keep default */
      }
      reject(new Error(detail));
    };
    xhr.onerror = () => {
      signal?.removeEventListener('abort', onAbort);
      reject(new Error('Cannot reach the backend. Check that the API server is running.'));
    };
    xhr.onabort = () => {
      signal?.removeEventListener('abort', onAbort);
      reject(new Error('Upload cancelled.'));
    };

    const form = new FormData();
    form.append('file', file, file.name);
    xhr.send(form);
  });
}

export function listInvoices(params: InvoiceListParams = {}): Promise<InvoiceListResponse> {
  const search = new URLSearchParams();
  if (params.search?.trim()) search.set('search', params.search.trim());
  if (params.decision) search.set('decision', params.decision);
  if (params.status) search.set('status', params.status);
  search.set('sort_by', params.sort_by ?? 'submission');
  search.set('sort_dir', params.sort_dir ?? 'desc');
  search.set('page', String(params.page ?? 1));
  search.set('page_size', String(params.page_size ?? 20));
  return apiGet<InvoiceListResponse>(`/invoices?${search.toString()}`, {});
}

export function getInvoice(invoiceId: number): Promise<InvoiceDetail> {
  return apiGet<InvoiceDetail>(`/invoices/${invoiceId}`);
}

export function invoiceDocumentUrl(invoiceId: number): string {
  return apiUrl(`/invoices/${invoiceId}/document`);
}

export function getDashboardSummary(): Promise<DashboardSummary> {
  return apiGet<DashboardSummary>('/dashboard/summary');
}

export function resetDemoData(): Promise<ResetResponse> {
  return apiPost<ResetResponse>('/dashboard/reset');
}
