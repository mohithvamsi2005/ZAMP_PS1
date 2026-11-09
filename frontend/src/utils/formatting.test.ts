import { describe, it, expect } from 'vitest';
import { money, dateShort, duration, fileSize, dateTime } from './formatting';

describe('formatting', () => {
  it('formats INR amounts with Indian grouping', () => {
    expect(money('60000.00')).toBe('₹60,000.00');
    expect(money('59000')).toBe('₹59,000.00');
    expect(money('12,34,567.50'.replace(/,/g, ''))).toBe('₹12,34,567.50');
  });

  it('returns placeholder for missing values', () => {
    expect(money(null)).toBe('—');
    expect(money(undefined)).toBe('—');
    expect(money('not-a-number')).toBe('—');
  });

  it('formats short dates in en-IN', () => {
    expect(dateShort('2026-11-09T16:09:38.338493+00:00')).toContain('2026');
    expect(dateShort('definitely broken')).toBe('—');
    expect(dateShort(null)).toBe('—');
  });

  it('formats full datetimes in en-IN', () => {
    const s = dateTime('2026-11-09T16:09:38.338493+00:00');
    expect(s).toContain('2026');
    expect(s).toMatch(/\d{2}:\d{2}/);
  });

  it('formats durations compactly', () => {
    expect(duration(0.4)).toBe('400 ms');
    expect(duration(9.96)).toBe('10.0 s');
    expect(duration(75)).toBe('1m 15s');
    expect(duration(null)).toBe('—');
  });

  it('formats file sizes', () => {
    expect(fileSize(512)).toBe('512 B');
    expect(fileSize(2048)).toBe('2.0 KB');
    expect(fileSize(3 * 1024 * 1024)).toBe('3.00 MB');
  });
});
