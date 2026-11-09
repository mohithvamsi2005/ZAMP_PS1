import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, act } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import UploadInvoice from './UploadInvoice';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { render } from '@testing-library/react';

class FakeXHR {
  static instances: FakeXHR[] = [];
  upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  status = 0;
  responseText = '';

  open() {}
  setRequestHeader() {}
  send() {
    FakeXHR.instances.push(this);
  }
  abort() {
    this.onabort?.();
  }
}

function renderWithRoutes() {
  return render(
    <MemoryRouter initialEntries={['/upload']}>
      <Routes>
        <Route path="/upload" element={<UploadInvoice />} />
        <Route path="/processing/:runId" element={<div>processing-probe</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

const pdfFile = () => new File(['%PDF-1.4 demo bytes'], 'invoice.pdf', { type: 'application/pdf' });

describe('Upload invoice', () => {
  beforeEach(() => {
    FakeXHR.instances = [];
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
  });

  it('rejects non-PDF files dropped onto the dropzone before any network traffic', async () => {
    // Note: the file picker's accept filter blocks non-PDFs in real browsers —
    // invalid files reach the UI via drag-and-drop, which is the path we test.
    renderWithRoutes();
    const dropzone = screen.getByRole('button', { name: /drop a pdf invoice/i });
    const txt = new File(['hello'], 'notes.txt', { type: 'text/plain' });
    const { fireEvent } = await import('@testing-library/react');
    fireEvent.drop(dropzone, { dataTransfer: { files: [txt] } });
    expect(await screen.findByText(/Only PDF files can be uploaded/)).toBeInTheDocument();
    expect(FakeXHR.instances).toHaveLength(0);
  });

  it('rejects empty files dropped onto the dropzone', async () => {
    renderWithRoutes();
    const dropzone = screen.getByRole('button', { name: /drop a pdf invoice/i });
    const empty = new File([], 'empty.pdf', { type: 'application/pdf' });
    const { fireEvent } = await import('@testing-library/react');
    fireEvent.drop(dropzone, { dataTransfer: { files: [empty] } });
    expect(await screen.findByText(/This file is empty/)).toBeInTheDocument();
    expect(FakeXHR.instances).toHaveLength(0);
  });

  it('rejects files over the 20 MB ceiling', async () => {
    renderWithRoutes();
    const dropzone = screen.getByRole('button', { name: /drop a pdf invoice/i });
    const big = new File([new Uint8Array(21 * 1024 * 1024)], 'big.pdf', { type: 'application/pdf' });
    const { fireEvent } = await import('@testing-library/react');
    fireEvent.drop(dropzone, { dataTransfer: { files: [big] } });
    expect(await screen.findByText(/20 MB or smaller/)).toBeInTheDocument();
    expect(FakeXHR.instances).toHaveLength(0);
  });

  it('uploads via XHR (202) and navigates to the live processing run', async () => {
    const { container } = renderWithRoutes();
    const input = container.querySelector('input[type=file]') as HTMLInputElement;
    await userEvent.upload(input, pdfFile());
    expect(screen.getByText('invoice.pdf')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /upload and process/i }));
    expect(FakeXHR.instances).toHaveLength(1);

    const inst = FakeXHR.instances[0];
    await act(async () => {
      inst.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 } as ProgressEvent);
      inst.status = 202;
      inst.responseText = JSON.stringify({ invoice_id: 9, run_id: 'run-abc-123', status: 'PENDING', message: 'Invoice uploaded and queued for processing.' });
      inst.onload?.();
    });

    expect(await screen.findByText('processing-probe')).toBeInTheDocument();
  });

  it('disables the submit button while uploading and ignores double clicks', async () => {
    const { container } = renderWithRoutes();
    const input = container.querySelector('input[type=file]') as HTMLInputElement;
    await userEvent.upload(input, pdfFile());

    const submit = screen.getByRole('button', { name: /upload and process/i });
    await userEvent.click(submit);
    await userEvent.click(submit); // double click — must not re-fire

    expect(FakeXHR.instances).toHaveLength(1);
    expect(screen.getByRole('button', { name: /sending/i })).toBeDisabled();
  });

  it('surfaces the backend validation message when the server rejects the PDF', async () => {
    const { container } = renderWithRoutes();
    const input = container.querySelector('input[type=file]') as HTMLInputElement;
    await userEvent.upload(input, pdfFile());
    await userEvent.click(screen.getByRole('button', { name: /upload and process/i }));

    const inst = FakeXHR.instances[0];
    await act(async () => {
      inst.status = 400;
      inst.responseText = JSON.stringify({ detail: 'Invalid PDF: File is not a valid PDF (missing %PDF header — probably not a real PDF)' });
      inst.onload?.();
    });

    expect(await screen.findByText(/missing %PDF header/i)).toBeInTheDocument();
  });
});
