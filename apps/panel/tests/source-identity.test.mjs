import test from 'node:test';
import assert from 'node:assert/strict';
import {snapshotPath, validateSnapshotIdentity} from '../src/source-identity.ts';
const id='12345678-1234-1234-1234-123456789abc';
const source={snapshot_id:id,source_id:'sec-edgar-revenue-v1',sha256:'a'.repeat(64),url:'https://data.sec.gov/public.json',retrieved_at:'2026-11-06T10:00:00Z',license:'SEC'};
const metadata={schema_version:'1.0',data_origin:'live',snapshot_id:id,instrument_id:id,source_id:source.source_id,sha256:source.sha256,source_url:source.url,retrieved_at:source.retrieved_at,license:source.license,byte_length:123,media_type:'application/json',as_of:source.retrieved_at,available_at:source.retrieved_at,created_at:source.retrieved_at};
test('matching metadata binds the original snapshot without changing it',()=>{
  assert.equal(validateSnapshotIdentity(source,id,metadata),metadata);
  assert.equal(snapshotPath(id),'/v1/snapshots/'+id);
});
test('a source identifier cannot escape the local snapshot path',()=>{
  for(const value of ['https://evil.example','../content',id+'/content',id+'?x=1','<script>'])assert.throws(()=>snapshotPath(value));
});
test('report identity mismatches block the download',()=>{
  for(const [key,value] of Object.entries({snapshot_id:'other',instrument_id:'other',source_id:'other',sha256:'b'.repeat(64),source_url:'https://evil.example',retrieved_at:'2026-11-05T10:00:00Z',license:'different'}))assert.throws(()=>validateSnapshotIdentity(source,id,{...metadata,[key]:value}));
});
test('malformed displayed fields cannot pass identity verification',()=>{
  for(const [key,value] of Object.entries({byte_length:NaN,media_type:'text/html',as_of:'invalid',available_at:undefined,created_at:'invalid'}))assert.throws(()=>validateSnapshotIdentity(source,id,{...metadata,[key]:value}));
  assert.throws(()=>validateSnapshotIdentity(source,id,null));
  assert.throws(()=>validateSnapshotIdentity(source,id,{...metadata,byte_length:1048577}));
  assert.throws(()=>validateSnapshotIdentity(source,id,{...metadata,data_origin:'unknown'}));
});
