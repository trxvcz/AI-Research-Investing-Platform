import test from 'node:test';
import assert from 'node:assert/strict';
import {completedAnalysis, shouldPollTask, assertTaskIdentity} from '../src/task-state.ts';
const task = (extra={}) => ({run_id:'task-1',symbol:'AAPL',status:'queued',stage:'queued',attempt:0,error_code:null,error_reason:null,created_at:'2026-11-09T00:00:00Z',updated_at:'2026-11-09T00:00:00Z',heartbeat_at:null,lease_expires_at:null,worker_id:null,instrument_id:null,report_id:null,revision:null,...extra});
test('queued and failed tasks never replace a displayed analysis',()=>{
 assert.equal(completedAnalysis(task()),undefined);
 assert.equal(completedAnalysis(task({status:'failed',instrument_id:'instrument',report_id:'report',revision:1})),undefined);
});
test('completed report opens only after all exact identifiers are present',()=>{
 assert.equal(completedAnalysis(task({status:'completed',instrument_id:'instrument'})),undefined);
 const result=completedAnalysis(task({status:'completed',instrument_id:'instrument',report_id:'report',revision:3}));
 assert.equal(result.report_id,'report');assert.equal(result.revision,3);assert.equal(result.run_id,'task-1');
});
test('automatic reads stop at their bound, on failure and on terminal state',()=>{
 assert.equal(shouldPollTask(task(),59,''),true);
 assert.equal(shouldPollTask(task(),60,''),false);
 assert.equal(shouldPollTask(task({status:'running'}),0,'connection failed'),false);
 assert.equal(shouldPollTask(task({status:'completed'}),0,''),false);
});
test('responses cannot silently switch task or company',()=>{
 assert.doesNotThrow(()=>assertTaskIdentity(task(),{run_id:'task-1',symbol:'AAPL'}));
 assert.throws(()=>assertTaskIdentity(task(),{run_id:'other',symbol:'AAPL'}));
 assert.throws(()=>assertTaskIdentity(task(),{run_id:'task-1',symbol:'MSFT'}));
});


test('an explicitly selected market must match the task response',()=>{
 assert.doesNotThrow(()=>assertTaskIdentity(task({exchange_mic:'XNAS'}),{run_id:'task-1',symbol:'AAPL',exchange_mic:'XNAS'}));
 assert.throws(()=>assertTaskIdentity(task({exchange_mic:'XNYS'}),{run_id:'task-1',symbol:'AAPL',exchange_mic:'XNAS'}));
});
