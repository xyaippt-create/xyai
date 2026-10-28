import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveFeedbackTarget } from '../../src/feedbackTarget.js';
test('color feedback rejects a previous 4K target',()=>{
 const stale={feature_key:'enhancement_4k',task_id:'4k_previous',result_id:'4k_result'};
 assert.equal(resolveFeedbackTarget(null,stale,'color_correction'),null);
 assert.equal(resolveFeedbackTarget(stale,null,'color_correction'),null);
});
test('failed color feedback uses the current task and keeps Result absent',()=>{
 const target={feature_key:'color_correction',module_id:'hdde.color.correction',task_id:'color_current'};
 assert.equal(resolveFeedbackTarget(target,{feature_key:'enhancement_4k',result_id:'4k_previous'},'color_correction'),target);
 assert.equal(resolveFeedbackTarget(target,null,'color_correction').result_id,undefined);
});
test('existing 4K feedback selection is preserved',()=>{
 const target={feature_key:'enhancement_4k',task_id:'4k_current'};
 assert.equal(resolveFeedbackTarget(null,target,'processing_center'),target);
});
