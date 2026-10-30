const fs = require('fs'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync(require('path').join(__dirname, '../src/main/resources/static/index.html'), 'utf8');
const rpeExpression = html.match(/const rpeVal = ([^;]+);/)[1];
for (const [parsedRpe, expected] of [[0,0],[NaN,0],[9,9]]) {
    assert.equal(vm.runInNewContext(rpeExpression,{parsedRpe,completed:true,targetRpe:8}),expected);
}
function load(ctx, name, async = false) {
    const start = html.indexOf(`        ${async ? 'async ' : ''}function ${name}(`);
    assert(start >= 0, name);
    vm.runInContext(html.slice(start, html.indexOf('\n        }', start) + 10), ctx);
}
async function test(kind) {
    let queue = [{submissionId:'old'}], calls = 0;
    const ctx = {console, Date, isFinishingWorkout:false, activeWorkoutDay:{},
        pendingWorkoutRetryInFlight:false, pendingCardioRetryInFlight:false,
        activeFinishPendingSubmissionId:null, activeCardioFinishPendingSubmissionId:null,
        PENDING_WORKOUT_BACKGROUND_RETRY_MS:15000, finishErrorMessage:()=> 'offline',
        showWorkoutSaveState:()=>{}, fetchBootstrap:async()=>{}, fetchCardioLogs:async()=>{},
        schedulePendingWorkoutRetry:()=>{}, schedulePendingCardioRetry:()=>{}};
    ctx[`loadPending${kind}Submissions`] = () => JSON.parse(JSON.stringify(queue));
    ctx[`savePending${kind}Submissions`] = items => (queue = items, true);
    ctx[`submit${kind}PayloadWithRetry`] = async () => {
        calls++; queue.push({submissionId:'new'}); return {};
    };
    vm.createContext(ctx);
    load(ctx, 'reconcilePendingSubmissions');
    load(ctx, `retryPending${kind}Submissions`, true);
    await ctx[`retryPending${kind}Submissions`]();
    assert.equal(calls, 1);
    assert.deepEqual(JSON.parse(JSON.stringify(queue)), [{submissionId:'new'}]);
    const started=[{submissionId:'x',value:1}];
    const failed=[{submissionId:'x',value:1,pendingAttempts:1}];
    assert.equal(ctx.reconcilePendingSubmissions(started, failed, []).length,0);
    assert.equal(ctx.reconcilePendingSubmissions(started, failed, [{submissionId:'x',value:2}])[0].value,2);
    assert.equal(ctx.reconcilePendingSubmissions(started, failed, started)[0].pendingAttempts,1);
    let saved;
    ctx.localStorage={setItem:(_, value)=>saved=JSON.parse(value),removeItem:()=>saved=[]};
    ctx.PENDING_WORKOUT_SUBMISSIONS_KEY='workout';
    ctx.PENDING_CARDIO_SUBMISSIONS_KEY='cardio';
    load(ctx, `savePending${kind}Submissions`);
    ctx[`savePending${kind}Submissions`](Array.from({length:12},(_,i)=>({submissionId:String(i)})));
    assert.equal(saved.length,12);
    assert.equal(saved[0].submissionId,'0');
}
(async()=>{await test('Workout'); await test('Cardio'); console.log('pending queue concurrency, cancellation, changed payload and 12-item retention: PASS');})()
    .catch(error=>{console.error(error);process.exitCode=1;});
