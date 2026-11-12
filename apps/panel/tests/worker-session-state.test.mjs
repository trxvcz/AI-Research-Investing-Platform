import test from 'node:test';
import assert from 'node:assert/strict';
import {assertWorkerPage,observedWorkerStatus,shouldPollWorkerSessions,workerPageIdentity} from '../src/worker-session-state.ts';

const session={session_id:'session-1',kind:'document_validation',status:'online',started_at:'2026-11-10T10:00:00Z',heartbeat_at:'2026-11-10T10:00:10Z',observed_at:'2026-11-10T10:00:20Z',contact_expires_at:'2026-11-10T10:00:55Z',stopped_at:null,stop_reason:null};
const page={items:[session],observed_at:session.observed_at,stale_after_seconds:45,next_after_id:null};

test('process contact expires on the exact observed deadline without using client wall time',()=>{
  assert.equal(observedWorkerStatus(session,34999,false),'online');
  assert.equal(observedWorkerStatus(session,35000,false),'unknown');
  assert.equal(observedWorkerStatus(session,999999,false),'unknown');
  for(const age of [-1,NaN,Infinity])assert.equal(observedWorkerStatus(session,age,false),'unknown');
});

test('paused failed or exhausted observation never retains an online claim',()=>{
  assert.equal(observedWorkerStatus(session,0,true),'unknown');
  assert.equal(observedWorkerStatus({...session,status:'stale'},99999,true),'stale');
  assert.equal(observedWorkerStatus({...session,status:'stopped'},99999,true),'stopped');
});

test('idle or empty pages can be polled but read count and errors remain bounded',()=>{
  assert.equal(shouldPollWorkerSessions(0,'',false),true);
  assert.equal(shouldPollWorkerSessions(28,'',false),true);
  assert.equal(shouldPollWorkerSessions(29,'',false),false);
  assert.equal(shouldPollWorkerSessions(0,'network failure',false),false);
  assert.equal(shouldPollWorkerSessions(0,'',true),false);
  for(const read of [-1,1.5,NaN])assert.equal(shouldPollWorkerSessions(read,'',false),false);
});

test('page identity separates filters and cursors including ambiguous delimiters',()=>{
  assert.notEqual(workerPageIdentity('','sec_import'),workerPageIdentity('sec_import',''));
  assert.notEqual(workerPageIdentity('sec_import','cursor-a'),workerPageIdentity('document_validation','cursor-a'));
  assert.equal(workerPageIdentity('','cursor-a'),workerPageIdentity('','cursor-a'));
});

test('responses must match filter common observation and unique process sessions',()=>{
  assert.doesNotThrow(()=>assertWorkerPage(page,'document_validation'));
  assert.throws(()=>assertWorkerPage(page,'sec_import'));
  assert.throws(()=>assertWorkerPage({...page,items:[session,session]},''));
  assert.throws(()=>assertWorkerPage({...page,observed_at:'2026-11-10T10:00:21Z'},''));
  assert.throws(()=>assertWorkerPage({...page,stale_after_seconds:60},''));
});

test('malformed deadlines inconsistent states and impossible chronology fail closed',()=>{
  for(const update of [{status:'stopped'},{status:'stale'},{heartbeat_at:'2026-11-10T10:01:00Z'},{contact_expires_at:'invalid'},{contact_expires_at:'2026-11-10T10:00:54Z'},{stopped_at:'2026-11-10T10:00:15Z'}]){
    assert.throws(()=>assertWorkerPage({...page,items:[{...session,...update}]},''));
  }
  const stopped={...session,status:'stopped',stopped_at:'2026-11-10T10:00:18Z',stop_reason:'completed'};
  assert.doesNotThrow(()=>assertWorkerPage({...page,items:[stopped]},''));
  const stale={...session,status:'stale',observed_at:'2026-11-10T10:00:55Z'};
  assert.doesNotThrow(()=>assertWorkerPage({...page,observed_at:stale.observed_at,items:[stale]},''));
});
