import test from 'node:test';
import assert from 'node:assert/strict';
import {assertArchiveIdentity, assertReviewIdentity, bytesToBase64, checkChronology, explicitTimestamp, latestReviews, MAX_DOCUMENT_BYTES, MAX_DRAFT_BYTES, requireFileSize, selectImportAttempt} from '../src/document-archive-state.ts';

test('file limits reject empty, oversized and invalid sizes before reading',()=>{
  for(const size of [0,-1,NaN,Infinity,1.5,MAX_DOCUMENT_BYTES+1])assert.throws(()=>requireFileSize(size,MAX_DOCUMENT_BYTES));
  assert.doesNotThrow(()=>requireFileSize(MAX_DOCUMENT_BYTES,MAX_DOCUMENT_BYTES));
  assert.throws(()=>requireFileSize(MAX_DRAFT_BYTES+1,MAX_DRAFT_BYTES));
});

test('binary document encoding preserves all byte values and avoids text transcoding',()=>{
  const bytes=Uint8Array.from({length:32769},(_,index)=>index%256);
  assert.deepEqual(Buffer.from(bytesToBase64(bytes),'base64'),Buffer.from(bytes));
  assert.throws(()=>bytesToBase64(new Uint8Array()));
});

test('dates require a real calendar date, explicit zone and bounded precision',()=>{
  for(const raw of ['2026-11-10T12:00:00','2026-02-29T12:00:00Z','2026-04-31T12:00:00Z','2026-13-01T12:00:00Z','2026-11-10T24:00:00Z','2026-11-10T12:00:00+24:00','2026-11-10T12:00:00.1234567Z','0000-01-01T00:00:00Z'])assert.throws(()=>explicitTimestamp(raw));
  assert.equal(explicitTimestamp('2024-02-29T12:00:00.123456+01:00'),'2024-02-29T12:00:00.123456+01:00');
});

test('availability compares offsets and microseconds without silent millisecond truncation',()=>{
  assert.doesNotThrow(()=>checkChronology('2026-11-10T12:00:00+01:00','2026-11-10T11:00:00Z'));
  assert.throws(()=>checkChronology('2026-11-10T11:00:00.000002Z','2026-11-10T11:00:00.000001Z'));
  assert.doesNotThrow(()=>checkChronology('2026-11-10T11:00:00.123455Z','2026-11-10T12:00:00.123456+01:00'));
});

test('an ambiguous import retry retains exact UUID and payload, never starts another operation',()=>{
  const payload={title:'Dokument',instrument_id:null,format:'text',classification:'private',content_base64:'MTI=',draft_json:'{}',provider_id:'offline-import',model_id:null,prompt_version:null,source_available_at:'2026-11-10T11:00:00Z',as_of:'2026-11-10T11:00:00Z'};
  const first=selectImportAttempt(payload,undefined,()=> 'archive-one');
  assert.equal(selectImportAttempt(payload,first,()=>{throw Error('must not generate retry UUID');}),first);
  assert.throws(()=>selectImportAttempt({...payload,draft_json:'{"facts":[]}'},first,()=> 'archive-two'));
  assert.equal(selectImportAttempt({...payload,title:'Inny'},undefined,()=> 'archive-two').archive_id,'archive-two');
});

test('a document response must match archive, packet and result identities',()=>{
  const record={archive_id:'a',packet:{document_id:'a'},result:{document_id:'a'}};
  assert.doesNotThrow(()=>assertArchiveIdentity(record,'a'));
  assert.throws(()=>assertArchiveIdentity(record,'b'));
  assert.throws(()=>assertArchiveIdentity({...record,packet:{document_id:'b'}},'a'));
  assert.throws(()=>assertArchiveIdentity({...record,result:{document_id:'b'}},'a'));
});

test('latest verdict uses the highest revision and preserves older events',()=>{
  const first={revision:1,command:{fact_index:0,verdict:'accepted'},reviewed_at:'2026-11-10T11:00:00Z'};
  const second={revision:2,command:{fact_index:1,verdict:'accepted'},reviewed_at:'2026-11-10T11:00:01Z'};
  const correction={revision:3,command:{fact_index:0,verdict:'rejected'},reviewed_at:'2026-11-10T11:00:02Z'};
  const events=[correction,first,second];
  const latest=latestReviews(events);
  assert.equal(latest.get(0),correction);assert.equal(latest.get(1),second);
  assert.deepEqual(events,[correction,first,second]);
});

test('review response must identify the exact command, frozen version and decision',()=>{
  const command={command_id:'c',expected_revision:3,fact_index:0,verdict:'accepted',note:'Sprawdzono okres i zakres.'};
  const event={revision:4,command:{note:command.note,verdict:'accepted',fact_index:0,expected_revision:3,command_id:'c'},reviewed_at:'2026-11-10T11:00:00Z'};
  assert.doesNotThrow(()=>assertReviewIdentity(event,command));
  assert.throws(()=>assertReviewIdentity({...event,revision:5},command));
  assert.throws(()=>assertReviewIdentity({...event,command:{...command,command_id:'other'}},command));
  assert.throws(()=>assertReviewIdentity({...event,command:{...command,verdict:'rejected'}},command));
  assert.throws(()=>assertReviewIdentity({...event,command:{...command,note:'Inna decyzja'}},command));
});
