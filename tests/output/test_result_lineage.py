import hashlib
import json
import unittest
from pathlib import Path

from tests.output import test_continue_processing as workflow
from engine.storage.result_reuse import ResultReuseError, resolve_reusable_result_source, result_lineage


class ResultLineageTests(unittest.TestCase):
    setUp = workflow.ContinueProcessingWorkflowTests.setUp
    tearDown = workflow.ContinueProcessingWorkflowTests.tearDown
    user_dirs = workflow.ContinueProcessingWorkflowTests.user_dirs
    build_app = workflow.ContinueProcessingWorkflowTests.build_app

    def compression_round(self, result_id=None, short_side=60, fail=False):
        if result_id:
            response=self.client.post('/api/image-compression/intake-result',json={'result_id':result_id})
        else:
            response=self.client.post('/api/image-compression/intake',files={'file':('initial.png',workflow.image_bytes((240,160)),'image/png')})
        self.assertEqual(response.status_code,200,response.text)
        intake=response.json()['data']
        response=self.client.post('/api/image-compression/run',json={'source_token':intake['source_token'],
            'operation_mode':'UPLOAD_ADAPTATION' if fail else 'RESIZE_REDUCTION',
            'params':{'max_file_size_bytes':1} if fail else {'target_short_side':short_side}})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['data']['task'],intake

    def watermark(self, result_id):
        response=self.client.post('/api/batch-watermark/batches',data={'result_ids_json':json.dumps([result_id]),'spec_json':'{"kind":"text","text":"OC04"}'})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['data']['items'][0]

    def test_three_real_rounds_trace_original_source_after_task_and_list_removal(self):
        first,intake=self.compression_round(short_side=120)
        second=self.watermark(first['result_id'])
        third,_=self.compression_round(second['result_id'],short_side=60)
        trace=result_lineage(self.registry,third['result_id'])
        self.assertEqual(trace['round_count'],3)
        self.assertEqual([r['result_id'] for r in trace['items']],[first['result_id'],second['result_id'],third['result_id']])
        self.assertEqual(trace['initial_source']['sha256'],intake['source_sha256'])
        paths=[str(self.registry[x['task_id']]['source_path']) for x in (first,second,third)]
        self.assertEqual(len(set(paths)),3)
        hashes={str(self.registry[x['task_id']]['result_file']):self.registry[x['task_id']]['output_sha256'] for x in (first,second,third)}
        card=next(c for c in self.client.get('/api/output-center/items').json()['data']['items'] if c.get('result_id')==first['result_id'])
        self.assertEqual(self.client.post('/api/output-center/items/'+card['id']+'/clear').status_code,200)
        self.assertTrue(self.registry.delete_task_fact(second['task_id'])['deleted'])
        retained=self.registry[second['result_id']]
        self.assertEqual(retained['source_result_id'],first['result_id'])
        self.assertEqual(retained['source_task_id'],first['task_id'])
        self.assertEqual(result_lineage(self.registry,third['result_id']),trace)
        self.assertEqual(self.client.get('/api/output-center/results/'+third['result_id']+'/lineage').json()['data'],trace)
        self.assertEqual(hashes,{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in hashes})

    def test_failed_middle_round_recovery_and_two_branches_keep_distinct_identity(self):
        first,_=self.compression_round(short_side=120)
        failed,_=self.compression_round(first['result_id'],fail=True)
        self.assertEqual(failed['status'],'failed')
        self.assertFalse(failed['result_id'])
        left,left_source=self.compression_round(first['result_id'],short_side=80)
        right,right_source=self.compression_round(first['result_id'],short_side=60)
        self.assertNotEqual(left_source['source_token'],right_source['source_token'])
        self.assertNotEqual(left['task_id'],right['task_id'])
        self.assertNotEqual(left['result_id'],right['result_id'])
        for task in (left,right):
            trace=result_lineage(self.registry,task['result_id'])
            self.assertEqual(trace['round_count'],2)
            self.assertEqual(trace['items'][-1]['source_task_id'],first['task_id'])
            self.assertEqual(trace['items'][-1]['source_result_id'],first['result_id'])

    def test_pending_review_is_not_a_successful_reusable_source(self):
        first,_=self.compression_round(short_side=120)
        record=self.registry[first['task_id']]
        record['result_action']='REVIEW_REQUIRED';record['result_review_status']='pending';self.registry[first['task_id']]=record
        with self.assertRaises(ResultReuseError) as denied:
            resolve_reusable_result_source(self.registry,first['result_id'],self.formal,max_bytes=50*1024*1024,allowed_suffixes={'.png'})
        self.assertEqual(denied.exception.code,'RESULT_REUSE_NOT_ACCEPTED')
        self.assertEqual(self.client.get('/api/output-center/results/'+first['result_id']+'/lineage').status_code,409)
        page=self.client.get('/api/output-center/items').json()['data']
        card=next(c for c in page['items'] if c.get('result_id')==first['result_id'])
        self.assertFalse(card['continue_eligible'])

    def test_cycle_and_sha_edge_mismatch_fail_without_file_changes(self):
        first,_=self.compression_round(short_side=120)
        second,_=self.compression_round(first['result_id'],short_side=60)
        record=self.registry[second['task_id']];record['source_result_sha256']='0'*64;self.registry[second['task_id']]=record
        with self.assertRaises(ResultReuseError) as mismatch:result_lineage(self.registry,second['result_id'])
        self.assertEqual(mismatch.exception.code,'RESULT_LINEAGE_IDENTITY_MISMATCH')
        record['source_result_sha256']=self.registry[first['task_id']]['output_sha256'];self.registry[second['task_id']]=record
        root=self.registry[first['task_id']]
        root.update(source_origin='EXISTING_RESULT',source_result_id=second['result_id'],source_task_id=second['task_id'],source_result_sha256=record['output_sha256'])
        self.registry[first['task_id']]=root
        with self.assertRaises(ResultReuseError) as cycle:result_lineage(self.registry,second['result_id'])
        self.assertEqual(cycle.exception.code,'RESULT_LINEAGE_CYCLE')
