import { RouterProvider } from 'react-router-dom';
import { router } from './router';

const FUTURE = { v7_startTransition: true } as const;

export default function App() {
  return <RouterProvider router={router} future={FUTURE} />;
}
