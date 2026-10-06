const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const html = fs.readFileSync(path.join(__dirname, '../src/main/resources/static/index.html'), 'utf8');
let now = 100000, nextId = 1;
const timers = new Map();
const exercises = [{name:'힙 어브덕션',restSeconds:60},{name:'레그 컬',restSeconds:90}];
const ctx = {
    Date:{now:()=>now}, restTimerInterval:null, restTimerRemainingMs:0,
    restTimerTotalMs:0, restTimerEndsAt:0, restTimerPaused:false,
    activeRestExerciseIdx:null, restPickerExerciseIdx:0,
    getActiveWorkoutDayObj:()=>({exercises}), getExerciseRestSeconds:ex=>ex.restSeconds,
    setInterval:fn=>{const id=nextId++;timers.set(id,fn);return id;},
    clearInterval:id=>timers.delete(id), updateRestTimerToggle:()=>{},
    paintRestTimer:()=>{if(ctx.restTimerInterval && !ctx.restTimerPaused)ctx.restTimerRemainingMs=Math.max(0,ctx.restTimerEndsAt-now);},
    saveExerciseRestSecondsPreference:()=>{}, updateExerciseMeta:()=>{},
    scheduleActiveWorkoutDraftSave:()=>{}, closeRestPicker:()=>{ctx.restPickerExerciseIdx=null;}
};
vm.createContext(ctx);
for(const name of ['startRestTimerForExercise','stopRestTimer','toggleRestTimerPause','chooseExerciseRestSeconds','handleRejectedWorkoutFinish']){
    const start=html.indexOf(`        function ${name}(`);
    assert(start>=0,name);
    vm.runInContext(html.slice(start,html.indexOf('\n        }',start)+10),ctx);
}
ctx.startRestTimerForExercise(0);
now += 5000;ctx.paintRestTimer();assert.equal(ctx.restTimerRemainingMs,55000);
ctx.chooseExerciseRestSeconds(30);
assert.equal(ctx.restTimerRemainingMs,30000);assert.equal(ctx.restTimerEndsAt,now+30000);
assert.equal(timers.size,1);
now+=1000;ctx.paintRestTimer();assert.equal(ctx.restTimerRemainingMs,29000);
ctx.restPickerExerciseIdx=0;ctx.chooseExerciseRestSeconds(120);
assert.equal(ctx.restTimerRemainingMs,120000);
ctx.restPickerExerciseIdx=1;const deadline=ctx.restTimerEndsAt;ctx.chooseExerciseRestSeconds(45);
assert.equal(ctx.restTimerEndsAt,deadline);assert.equal(exercises[1].restSeconds,45);
ctx.toggleRestTimerPause();assert.equal(ctx.restTimerPaused,true);
ctx.restPickerExerciseIdx=0;ctx.chooseExerciseRestSeconds(30);
assert.equal(ctx.restTimerPaused,false);assert.equal(ctx.restTimerEndsAt,now+30000);
ctx.stopRestTimer();ctx.restPickerExerciseIdx=0;ctx.chooseExerciseRestSeconds(60);
assert.equal(timers.size,0);assert.equal(ctx.restTimerRemainingMs,0);
ctx.chooseExerciseRestSeconds(-10);assert.equal(exercises[0].restSeconds,60);
const calls=[];
ctx.saveActiveWorkoutDraftSync=()=>calls.push('draft');
ctx.removePendingWorkoutSubmission=id=>calls.push(id);
ctx.setFinishButtonSaving=value=>calls.push(value);
ctx.alert=()=>calls.push('alert');ctx.finishErrorMessage=err=>err.message;
assert.equal(ctx.handleRejectedWorkoutFinish({retryable:true},'keep'),false);
assert.equal(calls.length,0);
assert.equal(ctx.handleRejectedWorkoutFinish({retryable:false,message:'invalid'},'rejected'),true);
assert.deepEqual(calls,['draft','rejected',false,'alert']);
console.log('rest restart, pause, other exercise, idle, and rejected save: PASS');
