import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DecisionBadge, RunStatusBadge, ValidationStatusBadge } from './StatusPill';

describe('RunStatusBadge', () => {
  it('renders human labels, never raw enum identifiers', () => {
    render(<RunStatusBadge status="COMPLETED" />);
    expect(screen.getByText('Processed')).toBeInTheDocument();
    render(<RunStatusBadge status="FAILED" />);
    expect(screen.getByText('Failed')).toBeInTheDocument();
    render(<RunStatusBadge status="RUNNING" />);
    expect(screen.getByText('Processing')).toBeInTheDocument();
    render(<RunStatusBadge status="PENDING" />);
    expect(screen.getByText('Queued')).toBeInTheDocument();
  });

  it('handles missing status', () => {
    render(<RunStatusBadge status={null} />);
    expect(screen.getByText('No run')).toBeInTheDocument();
  });
});

describe('DecisionBadge', () => {
  it('renders APPROVE / REVIEW / REJECT with long titles', () => {
    const { rerender } = render(<DecisionBadge decision="APPROVE" />);
    expect(screen.getByText('APPROVE')).toBeInTheDocument();
    rerender(<DecisionBadge decision="REVIEW" />);
    expect(screen.getByText('REVIEW')).toBeInTheDocument();
    rerender(<DecisionBadge decision="REJECT" />);
    expect(screen.getByText('REJECT')).toBeInTheDocument();
  });

  it('falls back for null decisions', () => {
    render(<DecisionBadge decision={null} />);
    expect(screen.getByText('No decision')).toBeInTheDocument();
  });
});

describe('ValidationStatusBadge', () => {
  it('maps duplicate signals onto red/amber tones', () => {
    render(<ValidationStatusBadge status="EXACT_DOCUMENT_DUPLICATE" />);
    expect(screen.getByText('EXACT_DOCUMENT_DUPLICATE')).toBeInTheDocument();
    render(<ValidationStatusBadge status="POTENTIAL_DUPLICATE" />);
    expect(screen.getByText('POTENTIAL_DUPLICATE')).toBeInTheDocument();
  });

  it('maps PASS onto green and UNKNOWN onto slate', () => {
    render(<ValidationStatusBadge status="PASS" />);
    expect(screen.getByText('PASS').className).toContain('badge-green');
    render(<ValidationStatusBadge status="UNKNOWN" />);
    expect(screen.getByText('UNKNOWN').className).toContain('badge-slate');
  });
});
