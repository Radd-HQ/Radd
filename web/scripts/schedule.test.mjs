import test from 'node:test';
import assert from 'node:assert/strict';
import {importTs} from './lib/load-ts.mjs';
const {defaultSchedule,isScheduleValid,ScheduleKind}=await importTs('web/packages/plugin-sdk/src/schedule.ts');
test('default schedules are complete and independent drafts',()=>{
 for(const kind of Object.values(ScheduleKind))assert(isScheduleValid(defaultSchedule(kind)));
 const first=defaultSchedule('weekly');first.weekdays.push(5);
 assert.deepEqual(defaultSchedule('weekly').weekdays,[0]);
});
test('form completeness rejects empty and out-of-range schedules without pretending to parse cron',()=>{
 for(const minutes of [null,0,1,-5,5.5])assert(!isScheduleValid({kind:'interval',minutes}));
 assert(isScheduleValid({kind:'interval',minutes:7}));
 for(const time of ['',null,'25:00','09:99'])assert(!isScheduleValid({kind:'daily',time}));
 for(const weekdays of [[],[7],[1,1],[-1],[1.5]])assert(!isScheduleValid({kind:'weekly',time:'09:00',weekdays}));
 for(const day of [0,32,1.5])assert(!isScheduleValid({kind:'monthly',time:'09:00',day}));
 assert(!isScheduleValid({kind:'cron',expression:'  '}));
 assert(isScheduleValid({kind:'cron',expression:'server validates this'}));
 assert(!isScheduleValid({kind:'future',time:'09:00'}));
});
