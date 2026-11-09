import { createBrowserRouter, redirect } from 'react-router-dom';
import { AppShell } from './components/layout/AppShell';
import Overview from './pages/Overview';
import Invoices from './pages/Invoices';
import InvoiceDetails from './pages/InvoiceDetails';
import UploadInvoice from './pages/UploadInvoice';
import ProcessingRun from './pages/ProcessingRun';
import ReviewQueue from './pages/ReviewQueue';
import History from './pages/History';
import NotFound from './pages/NotFound';

export const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <AppShell />,
      children: [
        { index: true, element: <Overview /> },
        { path: 'invoices', element: <Invoices /> },
        { path: 'invoices/:invoiceId', element: <InvoiceDetails /> },
        { path: 'upload', element: <UploadInvoice /> },
        { path: 'processing/:runId', element: <ProcessingRun /> },
        { path: 'review', element: <ReviewQueue /> },
        { path: 'runs', element: <History /> },
        { path: 'history', loader: () => redirect('/runs') },
        { path: '*', element: <NotFound /> },
      ],
    },
  ],
  {
    future: {
      v7_relativeSplatPath: true,
    },
  },
)
