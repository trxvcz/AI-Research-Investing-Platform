import test from 'node:test';
import assert from 'node:assert/strict';
import {isSupported, parseAttempt, parseAttempts, selectAttempt} from '../src/launch-state.ts';
const id = '01932abc-1234-4321-8765-0123456789ab';
test('network retries reuse the exact operation identity', () => {
 const previous = {symbol:'GOOGL',run_id:id};
 assert.strictEqual(selectAttempt(' googl ', previous, () => {throw Error('must not allocate');}), previous);
});
test('an unresolved operation cannot be silently replaced by another company', () => {
 assert.throws(() => selectAttempt('AAPL', {symbol:'GOOGL',run_id:id}, () => id));
});
test('new explicit request normalizes a supported symbol', () => {
 assert.deepEqual(selectAttempt(' googl ', undefined, () => id), {symbol:'GOOGL',run_id:id});
 assert.equal(isSupported('MSFT'), true);
 assert.throws(() => selectAttempt('https://evil', undefined, () => id));
});
test('reload recovers only valid operation identities and never creates a request', () => {
 assert.deepEqual(parseAttempt(JSON.stringify({symbol:'GOOGL',run_id:id})), {symbol:'GOOGL',run_id:id});
 for(const raw of [null, '{}', 'bad', JSON.stringify({symbol:'../MSFT',run_id:id}), JSON.stringify({symbol:'GOOGL',run_id:'url'})]) assert.equal(parseAttempt(raw), undefined);
});

test('parked requests retain valid identities after reload and deduplicate symbols', () => {
 const previous = {symbol:'GOOGL',run_id:id};
 const history = parseAttempts(JSON.stringify([previous, previous, {symbol:'../evil',run_id:id}]));
 assert.deepEqual(history, [previous]);
 assert.deepEqual(selectAttempt('GOOGL', history[0], () => {throw Error('must not allocate');}), previous);
 assert.deepEqual(parseAttempts('{}'), []);
});


test('catalog tickers preserve retry identities while rejecting URLs and unbounded text', () => {
 for (const symbol of ['MSFT','BRK-B','BRK.B']) {
  const attempt = selectAttempt(symbol, undefined, () => id);
  assert.deepEqual(parseAttempt(JSON.stringify(attempt)), attempt);
 }
 for (const symbol of ['../MSFT','https://sec.gov','A B','A'.repeat(17),'']) assert.equal(isSupported(symbol), false);
});


test('market is part of retry identity and separate markets allocate separate requests',()=>{
 const nasdaq=selectAttempt('ABC',undefined,()=>id,'XNAS');
 assert.strictEqual(selectAttempt('ABC',nasdaq,()=>{throw Error('new id');},'XNAS'),nasdaq);
 assert.throws(()=>selectAttempt('ABC',nasdaq,()=>id,'XNYS'));
 const nyse=selectAttempt('ABC',undefined,()=> '01932abc-1234-4321-8765-0123456789ac','XNYS');
 assert.notEqual(nasdaq.run_id,nyse.run_id);
 assert.equal(parseAttempts(JSON.stringify([nasdaq,nyse])).length,2);
 assert.deepEqual(parseAttempt(JSON.stringify(nasdaq)),nasdaq);
 assert.equal(parseAttempt(JSON.stringify({...nasdaq,exchange_mic:'EVIL'})),undefined);
});
