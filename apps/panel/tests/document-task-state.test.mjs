import test from 'node:test';
import assert from 'node:assert/strict';
import {assertDocumentTaskDetail,assertDocumentTaskIdentity,documentTaskAttempt,documentTaskRefreshIdentity,shouldPollDocumentTasks} from '../src/document-task-state.ts';

const attempt={job_id:'job-1',archive_id:'archive-1',mode:'validate_saved_draft'};
const task={...attempt,status:'queued',input_sha256:'input-sha',result:null};
const audit={request_sha256:'input-sha',result:null,provider_called:false,cost_usd:'0',usage_status:'not_applicable',input_tokens:null,output_tokens:null,model_id:null,prompt_version:null,response_sha256:null};
const detail={task,events:[],audits:[audit]};

test('manual refresh resets polling without colliding with the audit read identity',()=>{
  assert.notEqual(documentTaskRefreshIdentity(0,1,0),documentTaskRefreshIdentity(1,0,0));
  assert.notEqual(documentTaskRefreshIdentity(0,1,0),documentTaskRefreshIdentity(0,0,1));
  assert.equal(documentTaskRefreshIdentity(2,3,4),documentTaskRefreshIdentity(2,3,4));
});

test('document job retries preserve both exact UUID and archived source',()=>{
  assert.equal(documentTaskAttempt('archive-1',attempt,()=>{throw Error('must not create UUID');}),attempt);
  assert.throws(()=>documentTaskAttempt('other-archive',attempt,()=>''));
  assert.throws(()=>documentTaskAttempt('archive-1',{...attempt,mode:'model_extract'},()=>''));
  assert.deepEqual(documentTaskAttempt('archive-2',undefined,()=> 'new-job'),{job_id:'new-job',archive_id:'archive-2',mode:'validate_saved_draft'});
});

test('queue responses cannot switch job, archive or execution mode',()=>{
  assert.doesNotThrow(()=>assertDocumentTaskIdentity(task,attempt));
  for(const update of [{job_id:'other'},{archive_id:'other'},{mode:'model_extract'}])assert.throws(()=>assertDocumentTaskIdentity({...task,...update},attempt));
});

test('polling is bounded to initial read plus 29 refreshes and stops after errors or completion',()=>{
  assert.equal(shouldPollDocumentTasks([task],28,''),true);
  assert.equal(shouldPollDocumentTasks([task],29,''),false);
  assert.equal(shouldPollDocumentTasks([{status:'running'}],0,''),true);
  assert.equal(shouldPollDocumentTasks([{status:'running'}],0,'timeout'),false);
  for(const status of ['completed','failed','blocked'])assert.equal(shouldPollDocumentTasks([{status}],0,''),false);
  assert.equal(shouldPollDocumentTasks([],0,''),false);
});

test('audit and result identities stay bound to the frozen document input',()=>{
  assert.doesNotThrow(()=>assertDocumentTaskDetail(detail,'job-1'));
  assert.throws(()=>assertDocumentTaskDetail(detail,'other'));
  assert.throws(()=>assertDocumentTaskDetail({...detail,task:{...task,result:{document_id:'other'}}},'job-1'));
  assert.throws(()=>assertDocumentTaskDetail({...detail,audits:[{...audit,request_sha256:'other'}]},'job-1'));
  assert.throws(()=>assertDocumentTaskDetail({...detail,audits:[{...audit,result:{document_id:'other'}}]},'job-1'));
});

test('offline audit never silently accepts claimed model calls, fabricated token zeroes or costs',()=>{
  for(const update of [{provider_called:true},{cost_usd:'1'},{usage_status:'measured'},{input_tokens:0},{output_tokens:0},{model_id:'claimed-model'},{prompt_version:'claimed-prompt'},{response_sha256:'claimed-response'}]){
    assert.throws(()=>assertDocumentTaskDetail({...detail,audits:[{...audit,...update}]},'job-1'));
  }
});
