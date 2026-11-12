import test from 'node:test';
import assert from 'node:assert/strict';
import {choose} from '../services/runtime/router.mjs';

// Synthetic admission evidence; example.invalid is not a verified provider.
const now = Date.parse('2026-11-02T00:00:00Z');
const clock = {now};
function free(changes = {}) {
  return {
    id: 'synthetic-free', enabled: true, quality_pass: true, total_cost: 0,
    free_only_verified: true, paid_fallback: false, quota_remaining: 2,
    verified_at: '2026-11-01T00:00:00Z', verified_until: '2026-11-03T00:00:00Z',
    terms_reference: 'https://example.invalid/synthetic-terms', ...changes,
  };
}

test('a positive budget never admits paid selection or paid fallback', () => {
  for (const total_cost of [Number.MIN_VALUE, 0.01, 1000000]) {
    assert.throws(() => choose([free({total_cost})], Number.MAX_VALUE, clock), /free-only/);
  }
  assert.throws(() => choose([free({paid_fallback: true})], 100, clock), /free-only/);
  assert.equal(choose([free()], 0, clock).id, 'synthetic-free');
});

test('missing, malformed and unknown eligibility evidence fails closed', () => {
  const invalid = {
    enabled: [false, 1, 'true', null, undefined],
    quality_pass: [false, 1, null, undefined],
    total_cost: [null, undefined, '0', false, true, -1, NaN, Infinity, -Infinity],
    free_only_verified: [false, 1, null, undefined],
    paid_fallback: [true, 0, null, undefined],
    quota_remaining: [0, -1, 0.5, '2', true, Infinity, Number.MAX_SAFE_INTEGER + 1, undefined],
    id: ['', ' leading', 'trailing ', 'bad\u0000id', 'a'.repeat(129), 1, null],
    terms_reference: ['', undefined, 'http://example.invalid/terms',
      'https://user:secret@example.invalid/terms', 'https://example.invalid/terms\n',
      ' https://example.invalid/terms', 'not a URL', 'https://'],
  };
  for (const [field, values] of Object.entries(invalid)) {
    for (const value of values) {
      assert.throws(() => choose([free({[field]: value})], 100, clock), /free-only/,
        `${field}=${String(value)}`);
    }
  }
  for (const value of [null, false, 0, 'free', []]) {
    assert.throws(() => choose([value], 100, clock), /free-only/);
  }
});

test('verification boundaries use explicit UTC or offset times without calendar normalization', () => {
  assert.equal(choose([free({verified_at: '2026-11-02T01:00:00+01:00'})], 0, clock).id,
    'synthetic-free');
  assert.throws(() => choose([free({verified_at: '2026-11-02T00:00:00.001Z'})], 0, clock));
  assert.throws(() => choose([free({verified_until: '2026-11-02T00:00:00Z'})], 0, clock));
  assert.throws(() => choose([free({verified_until: '2026-11-01T23:59:59Z'})], 0, clock));
  assert.throws(() => choose([free({verified_at: '2026-11-03T00:00:00Z'})], 0, clock));
  const invalidTimes = [null, undefined, now, '2026-11-02', '2026-11-02T00:00:00',
    '2026-02-30T00:00:00Z', '2026-13-01T00:00:00Z', '2026-11-02T24:00:00Z',
    '2026-11-02T00:00:60Z', '2026-11-02T00:00:00+24:00',
    '2026-11-02T00:00:00+00:60', '2026-11-02T00:00:00Z\n',
    '2026-11-02T00:00:00.000001Z', '0000-11-02T00:00:00Z'];
  for (const value of invalidTimes) {
    for (const field of ['verified_at', 'verified_until']) {
      assert.throws(() => choose([free({[field]: value})], 0, clock), /free-only/);
    }
  }
});

test('invalid routing arguments do not silently enable a candidate', () => {
  for (const budget of [null, undefined, '0', true, -1, NaN, Infinity]) {
    assert.throws(() => choose([free()], budget, clock), /parameters/);
  }
  for (const badNow of [null, true, '0', NaN, Infinity, now + 0.5]) {
    assert.throws(() => choose([free()], 0, {now: badNow}), /parameters/);
  }
  assert.throws(() => choose(null, 0, clock), /parameters/);
  assert.throws(() => choose([], 0, clock), /free-only/);
});

test('selection is deterministic and leaves caller arrays and quota untouched', () => {
  const candidates = [free({id: 'z'}), free({id: 'a'}), free({id: 'paid', total_cost: 0.01})];
  const copy = structuredClone(candidates);
  assert.equal(choose(candidates, 100, clock).id, 'a');
  assert.deepEqual(candidates, copy);
  assert.equal(choose(candidates, 100, clock).quota_remaining, 2);
});
