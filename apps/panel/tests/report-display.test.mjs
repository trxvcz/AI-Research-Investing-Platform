import test from 'node:test';
import assert from 'node:assert/strict';
import {observationPeriod, metricLabels} from '../src/report-display.ts';
test('balance sheet point is shown as a state at one date', () => {
  assert.match(observationPeriod('2025-12-31T00:00:00Z', '2025-12-31T00:00:00Z'), /^Stan na /);
  assert.doesNotMatch(observationPeriod('2025-12-31T00:00:00Z', '2025-12-31T00:00:00Z'), / – /);
});
test('cash flow period remains an annual date range', () => {
  assert.match(observationPeriod('2025-01-01T00:00:00Z', '2025-12-31T00:00:00Z'), / – /);
  assert.doesNotMatch(observationPeriod('2025-01-01T00:00:00Z', '2025-12-31T00:00:00Z'), /^Stan na /);
  assert.match(metricLabels.long_term_debt_current, /część bieżąca/);
});
