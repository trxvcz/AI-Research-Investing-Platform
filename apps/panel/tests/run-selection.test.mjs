import test from 'node:test';
import assert from 'node:assert/strict';
import {selectReportRun} from '../src/run-selection.ts';

const old = {run_id:'old', status:'completed', created_at:'2026-11-09T15:00:00Z', report_id:'report-old', revision:1};
const newer = {run_id:'newer', status:'completed', created_at:'2026-11-11T10:00:00Z', report_id:'report-newer', revision:1};
const running = {run_id:'running', status:'running', created_at:'2026-11-11T11:00:00Z', report_id:null, revision:null};

test('initial report selection opens newest completed report regardless of API row order', () => {
  const items = [old, running, newer];
  assert.equal(selectReportRun(items, ''), newer);
  assert.deepEqual(items, [old, running, newer]);
  assert.equal(selectReportRun([newer, old, running], ''), newer);
});

test('manual selection and exact newly launched run take priority over newest completed report', () => {
  assert.equal(selectReportRun([old, newer, running], 'old'), old);
  assert.equal(selectReportRun([old, newer, running], 'running'), running);
  const started = {...running, run_id:'started', created_at:null};
  assert.equal(selectReportRun([started, old, newer], 'started'), started);
});

test('default report selection compares actual instants and requires an available report revision', () => {
  const offset = {...newer, run_id:'offset', created_at:'2026-11-11T11:30:00+02:00'};
  const missingReport = {...newer, run_id:'missing-report', created_at:'2026-11-11T12:00:00Z', report_id:null};
  const missingRevision = {...missingReport, run_id:'missing-revision', report_id:'orphan', revision:null};
  assert.equal(selectReportRun([offset, missingReport, missingRevision, newer], ''), newer);
});

test('pages without a completed report show newest available run and empty pages remain empty', () => {
  const unknownDate = {...running, run_id:'unknown', created_at:null};
  assert.equal(selectReportRun([unknownDate, running], ''), running);
  assert.equal(selectReportRun([], ''), undefined);
});
