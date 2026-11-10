import test from 'node:test';
import assert from 'node:assert/strict';
import {compareReports} from '../src/report-compare.ts';
const observation = (value=100, extra={}) => ({metric:'revenue',unit:'currency',currency:'USD',period_start:'2025-01-01T00:00:00Z',period_end:'2025-12-31T00:00:00Z',status:'available',value,...extra});
const report = (observations, extra={}) => ({methodology_version:'v1',input:{instrument_id:'same',asset_type:'equity',data_origin:'live',as_of:'2026-01-01T00:00:00Z',observations},...extra});
test('same-context differences preserve negative deltas and exact zero',()=>{
  assert.equal(compareReports(report([observation()]),report([observation(80)])).rows[0].delta,-20);
  assert.equal(compareReports(report([observation()]),report([observation(80)])).rows[0].percent,-20);
  assert.equal(compareReports(report([observation()]),report([observation()])).rows[0].delta,0);
});
test('missing Alphabet revenue becoming available is not zero-based growth',()=>{
  const row=compareReports(report([observation(null,{status:'missing',reason:'No fact'})]),report([observation(402836000000)])).rows[0];
  assert.equal(row.delta,null);assert.equal(row.percent,null);assert.equal(row.left.status,'missing');
});
test('different periods, currencies and units remain separate unmatched rows',()=>{
  for(const change of [{period_end:'2024-12-31T00:00:00Z'},{currency:'EUR'},{unit:'shares'}]) {
    const result=compareReports(report([observation()]),report([observation(110,change)]));
    assert.equal(result.rows.length,2);assert.ok(result.rows.every(row=>row.delta===null));
  }
});
test('duplicate contexts are ambiguous even if numeric values match',()=>{
  const row=compareReports(report([observation(),observation()]),report([observation(120)])).rows[0];
  assert.equal(row.delta,null);assert.equal(row.left,null);assert.match(row.reason,/Niejednoznaczne/);
});
test('zero and negative baseline allow delta but suppress percentage',()=>{
  for(const value of [0,-100]){const row=compareReports(report([observation(value)]),report([observation(10)])).rows[0];assert.equal(row.delta,10-value);assert.equal(row.percent,null);}
});
test('overflow and nonfinite inputs never produce numeric differences',()=>{
  for(const [before,after] of [[-Number.MAX_VALUE,Number.MAX_VALUE],[Infinity,1]]) {
    const row=compareReports(report([observation(before)]),report([observation(after)])).rows[0];
    assert.equal(row.delta,null);assert.equal(row.percent,null);
  }
});
test('instrument, origin and asset mismatch reject comparison',()=>{
  for(const change of [{instrument_id:'other'},{data_origin:'synthetic'},{asset_type:'etf'}]) {
    const a=report([observation()]),b=report([observation()]);Object.assign(b.input,change);
    assert.throws(()=>compareReports(a,b),/tego samego/);
  }
});
test('methodology and cutoff differences are visible warnings',()=>{
  const a=report([observation()]),b=report([observation()],{methodology_version:'v2'});b.input.as_of='2026-02-01T00:00:00Z';
  assert.equal(compareReports(a,b).warnings.length,3);
});
