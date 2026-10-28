import test from 'node:test';
import assert from 'node:assert/strict';
import { TARGET_FORMAT_OPTIONS, buildCompressionRequestPlan, targetFormatHelper } from '../../src/compressionParams.js';
import { createCompressionBatch, BATCH_STORAGE_KEY } from '../../src/batchCompression.js';

test('explicit JPG uses one request policy for every supported source format', () => {
  for (const format of ['PNG','JPEG','WEBP']) {
    const plan = buildCompressionRequestPlan({fileInfo:{format,width:640,height:360},mode:'DELIVERY_OPTIMIZATION',targetFormat:'JPEG'});
    assert.equal(plan.valid,true);
    assert.deepEqual(plan.params,{target_format:'JPEG'});
  }
  const plan = buildCompressionRequestPlan({fileInfo:{format:'WEBP'},mode:'DELIVERY_OPTIMIZATION'});
  assert.deepEqual(plan.params,{target_format:'SMART_COMPRESSION'});
});

test('batch conversion reports actual larger bytes without weakening compression-only validation', async () => {
  const id = 'compression_batch_'+'a'.repeat(32);
  for (const formatConversion of [true,false]) {
    const batch = createCompressionBatch({storage:{getItem:key=>key===BATCH_STORAGE_KEY?id:null},
      request:async()=>({data:{batchId:id,state:'COMPLETED',control:'RUNNING',running:false,revision:1,
        items:[{id:'one',taskId:'task',resultId:'result',status:'COMPLETED',originalBytes:100,finalBytes:150,
          savedPercent:-50,formatConversion,sourceSha256:'a'.repeat(64),outputSha256:'b'.repeat(64)}]}})});
    await batch.refresh();
    if (formatConversion) {
      assert.equal(batch.getSnapshot().items[0].savedPercent,-50);
      assert.equal(batch.getSnapshot().error,'');
    } else assert.match(batch.getSnapshot().error,/身份或状态不一致/);
  }
});

test('smart compression is the default and preserve format remains explicit', () => {
  const plan = buildCompressionRequestPlan({fileInfo:{format:'PNG'},mode:'DELIVERY_OPTIMIZATION'});
  assert.deepEqual(plan.params,{target_format:'SMART_COMPRESSION'});
  assert.deepEqual(TARGET_FORMAT_OPTIONS.map(({value,label})=>[value,label]),[
    ['SMART_COMPRESSION','智能压缩（推荐）'],['PRESERVE_FORMAT','保持原格式'],['JPEG','JPG'],['PNG','PNG'],['WEBP','WebP'],
  ]);
  assert.equal(targetFormatHelper('SMART_COMPRESSION'),'在安全范围内自动选择更小的合格结果；透明图片默认保留原格式。');
  assert.equal(targetFormatHelper('PRESERVE_FORMAT'),'保持原图片格式，仅优化当前格式。');
  assert.equal(targetFormatHelper('JPEG'),'统一输出为 JPG。');
  assert.equal(targetFormatHelper('PNG'),'统一输出为 PNG。');
  assert.match(targetFormatHelper('WEBP'),/部分软件可能不兼容/);
  for (const targetFormat of ['JPEG','PNG','WEBP']) {
    assert.deepEqual(buildCompressionRequestPlan({fileInfo:{format:'PNG'},mode:'DELIVERY_OPTIMIZATION',targetFormat}).params,{target_format:targetFormat});
  }
  for (const mode of ['LOSSLESS_COMPRESSION','RESIZE_REDUCTION','UPLOAD_ADAPTATION']) {
    assert.equal(buildCompressionRequestPlan({fileInfo:{format:'WEBP'},mode}).valid,false);
  }
});
