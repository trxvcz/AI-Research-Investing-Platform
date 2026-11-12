import test from 'node:test';
import assert from 'node:assert/strict';
import {buildHistoryChart} from '../src/history-chart-state.ts';
const point=(year,value)=>({period_start:year+'-01-01',period_end:year+'-12-31',value});
const close=(a,b)=>assert.ok(Math.abs(a-b)<0.001,`${a} != ${b}`);
test('positive values use date spacing and zero anchored heights',()=>{
 const layout=buildHistoryChart([point(2023,'10'),point(2024,'20'),point(2025,'30')]);
 assert.equal(layout.marks.length,3);assert.equal(layout.segments.length,1);assert.equal(layout.zeroY,layout.bottom);
 close(layout.marks[0].y,layout.bottom-(layout.bottom-layout.top)/3);assert.equal(layout.marks[2].y,layout.top);
 close((layout.marks[1].x-layout.left)/(layout.right-layout.left),366/731);
});
test('negative and mixed values fall on correct sides of zero',()=>{
 const l=buildHistoryChart([point(2023,'-10'),point(2024,'0'),point(2025,'10')]);
 assert.equal(l.marks[0].y,l.bottom);assert.equal(l.marks[2].y,l.top);assert.equal(l.marks[1].y,l.zeroY);
 assert.equal(l.zeroY,(l.top+l.bottom)/2);
 const negative=buildHistoryChart([point(2024,'-10')]);assert.equal(negative.zeroY,negative.top);
});
test('singletons are centered, constants and zero remain finite',()=>{
 const l=buildHistoryChart([point(2025,'0')]);assert.equal(l.marks[0].x,(l.left+l.right)/2);assert.equal(l.marks[0].y,l.zeroY);
 const constant=buildHistoryChart([point(2023,'4'),point(2024,'4')]);assert.equal(constant.marks[0].y,constant.marks[1].y);
});
test('null breaks segments and is never emitted as zero',()=>{
 const l=buildHistoryChart([point(2023,'5'),point(2024,null),point(2025,'8')]);
 assert.deepEqual(l.marks.map(p=>p.index),[0,2]);assert.deepEqual(l.segments.map(s=>s.length),[1,1]);
 assert.deepEqual(buildHistoryChart([point(2025,null)]).marks,[]);assert.deepEqual(buildHistoryChart([]).segments,[]);
});
test('absent years and changed annual scope break line even without explicit null',()=>{
 const gap=buildHistoryChart([point(2023,'5'),point(2025,'8')]);assert.deepEqual(gap.segments.map(s=>s.length),[1,1]);
 const changed={period_start:'2024-01-01',period_end:'2024-10-31',value:'8'};
 assert.deepEqual(buildHistoryChart([point(2023,'5'),changed]).segments.map(s=>s.length),[1,1]);
});
test('exact decimal labels survive huge values and imperceptible differences',()=>{
 const exact='900719925474099312345678901234567890';
 const l=buildHistoryChart([point(2023,exact),point(2024,exact.slice(0,-1)+'1')]);
 assert.equal(l.marks[0].value,exact);assert.equal(l.precisionLimited,true);
 for(const p of l.marks){assert.ok(Number.isFinite(p.x)&&Number.isFinite(p.y));assert.ok(p.y>=l.top&&p.y<=l.bottom);}
 const extreme=buildHistoryChart([point(2023,'9'.repeat(128)),point(2024,'0.'+'0'.repeat(125)+'1')]);assert.equal(extreme.marks.length,2);
});
test('invalid dates, order, syntax, magnitude and shapes are refused',()=>{
 for(const points of [null,{},[point(2025,'1e3')],[point(2025,'NaN')],[point(2025,Infinity)],[point(2025,'01')],[point(2025,'9'.repeat(129))],[{...point(2025,'2'),period_end:'2025-02-30'}],[{...point(2025,'2'),period_start:'0000-01-01'}],[{...point(2025,'2'),period_start:'2026-01-01'}],[point(2025,'1'),point(2025,'2')],[point(2025,'1'),point(2024,'2')],[null],[point(2022,'1'),point(2023,'1'),point(2024,'1'),point(2025,'1')]])assert.equal(buildHistoryChart(points),null);
});
test('layout never mutates source points including null reasons',()=>{
 const points=[point(2023,'10'),{...point(2024,null),reason:'MISSING_INPUT'},point(2025,'12')],original=structuredClone(points);
 points.forEach(Object.freeze);Object.freeze(points);const l=buildHistoryChart(points);assert.deepEqual(points,original);assert.notEqual(l.marks[0],points[0]);
});
