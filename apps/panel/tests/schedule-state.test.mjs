import test from 'node:test';
import assert from 'node:assert/strict';
import {assertOccurrences,assertScheduleCommand,assertScheduleCreated,assertTaskEvents,hoursToInterval,scheduleAttempt,scheduleReadIdentity,shouldPollSchedules} from '../src/schedule-state.ts';

const create={schedule_id:'s1',symbol:'GOOGL',exchange_mic:'XNAS',interval_seconds:86400,first_run_at:'2026-11-10T12:00:00.000001Z',enabled:false,refresh:false};
const record={schedule_id:'s1',template:{symbol:'GOOGL',exchange_mic:'XNAS',refresh:false},interval_seconds:86400,first_run_at:'2026-11-10T13:00:00.000001+01:00',revision:0,enabled:false};

test('hour bounds reject empty fractional and unbounded schedule intervals',()=>{
  assert.equal(hoursToInterval('1'),3600);assert.equal(hoursToInterval('720'),2592000);
  for(const value of ['',' ','0','721','1.5','NaN','Infinity'])assert.throws(()=>hoursToInterval(value));
});
test('ambiguous create retries preserve identity and frozen refresh, market and dates',()=>{
  const {schedule_id:_,...payload}=create;
  assert.equal(scheduleAttempt(payload,create,()=>{throw Error('new UUID forbidden');}),create);
  for(const change of [{refresh:true},{symbol:'AAPL'},{exchange_mic:'XNYS'},{interval_seconds:3600}])assert.throws(()=>scheduleAttempt({...payload,...change},create,()=>''));
  assert.equal(scheduleAttempt(payload,undefined,()=> 'fresh').schedule_id,'fresh');
});
test('create responses bind symbol market interval refresh and exact timestamp microseconds',()=>{
  assert.doesNotThrow(()=>assertScheduleCreated(record,create));
  for(const update of [{schedule_id:'other'},{interval_seconds:3600},{first_run_at:'2026-11-10T12:00:00.000002Z'},{template:{...record.template,refresh:true}},{template:{...record.template,exchange_mic:'XNYS'}}])assert.throws(()=>assertScheduleCreated({...record,...update},create));
});
test('command result recognizes committed retry even after a later control revision',()=>{
  const command={command_id:'c1',expected_revision:0,enabled:true};
  assert.doesNotThrow(()=>assertScheduleCommand({...record,revision:1,enabled:true},'s1',command));
  assert.doesNotThrow(()=>assertScheduleCommand({...record,revision:2,enabled:false},'s1',command));
  assert.throws(()=>assertScheduleCommand(record,'s1',command));
  assert.throws(()=>assertScheduleCommand({...record,revision:1,enabled:false},'s1',command));
  assert.throws(()=>assertScheduleCommand({...record,schedule_id:'other',revision:1,enabled:true},'s1',command));
  assert.throws(()=>assertScheduleCommand({...record,revision:undefined},'s1',command));
});
test('occurrences reject a missing queued task and unrelated or skipped sequence',()=>{
  const event={schedule_id:'s1',sequence:1,outcome:'enqueued',run_id:'r1',skipped_slots:3,scheduled_for:'2026-11-10T12:00:00Z',dispatched_at:'2026-11-10T12:00:01Z'};
  const page={schedule_id:'s1',items:[event],next_after_sequence:null};
  assert.doesNotThrow(()=>assertOccurrences(page,'s1',0));
  for(const update of [{run_id:null},{sequence:2},{schedule_id:'other'},{skipped_slots:-1},{outcome:'unknown',run_id:null},{dispatched_at:'2026-11-10T11:59:59Z'}])assert.throws(()=>assertOccurrences({...page,items:[{...event,...update}]},'s1',0));
  assert.doesNotThrow(()=>assertOccurrences({...page,items:[{...event,outcome:'skipped_busy',run_id:null}]},'s1',0));
});
test('SEC stage pages retain legacy coverage and enforce event and task identity',()=>{
  const event={run_id:'r1',sequence:1,kind:'legacy_snapshot',task:{run_id:'r1'}};
  const page={run_id:'r1',coverage:'legacy_snapshot',items:[event],next_after_sequence:null};
  assert.doesNotThrow(()=>assertTaskEvents(page,'r1',0));
  for(const change of [{run_id:'other'},{sequence:2},{task:{run_id:'other'}}])assert.throws(()=>assertTaskEvents({...page,items:[{...event,...change}]},'r1',0));
});
test('scheduler polling is bounded and refresh identities cannot collide after resetting poll',()=>{
  assert.equal(shouldPollSchedules(true,28,''),true);assert.equal(shouldPollSchedules(true,29,''),false);
  assert.equal(shouldPollSchedules(false,0,''),false);assert.equal(shouldPollSchedules(true,0,'timeout'),false);
  assert.notEqual(scheduleReadIdentity(0,1),scheduleReadIdentity(1,0));
});
