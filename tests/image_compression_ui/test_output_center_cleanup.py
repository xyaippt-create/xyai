"""Explicit record removal must preserve files, lineage and disjoint list scopes."""
import hashlib
import unittest
from pathlib import Path

from tests.image_compression_ui import test_batch_output_contract as batch_contract
source_bytes = batch_contract.source_bytes


class OutputCenterCleanupTests(unittest.TestCase):
    setUp = batch_contract.BatchOutputContractTests.setUp
    tearDown = batch_contract.BatchOutputContractTests.tearDown
    watermark = batch_contract.BatchOutputContractTests.watermark
    compression = batch_contract.BatchOutputContractTests.compression
    wait_batch = batch_contract.BatchOutputContractTests.wait_batch
    card = batch_contract.BatchOutputContractTests.card
    restart = batch_contract.BatchOutputContractTests.restart

    def page(self, scope="all"):
        response = self.client.get('/api/output-center/items', params={'scope':scope})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['data']

    def cleanup(self, scope, mode):
        response = self.client.post('/api/output-center/cleanup', json={'scope':scope,'mode':mode})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['data']['files_deleted'])
        return response.json()['data']

    def remove_test_file(self, item):
        path = Path(item['output_path']).resolve()
        self.assertTrue(path.is_relative_to(self.runtime.formal_root.resolve()))
        path.unlink()

    def test_partial_and_empty_batches_preserve_all_durable_identities(self):
        for feature in ('compression', 'watermark'):
            with self.subTest(feature=feature):
                if feature == 'watermark':
                    batch_id = self.watermark()['batch_id']
                else:
                    batch_id = self.compression([('files',(f'input-{i}.png',source_bytes(i),'image/png')) for i in range(3)])
                    self.wait_batch(batch_id)
                before = self.card(batch_id)
                self.assertEqual(before['summary']['completed'],3)
                self.remove_test_file(before['items'][0])
                missing = self.card(batch_id)['items'][0]
                self.assertEqual(missing['file_status'],'MISSING')
                cleared = self.client.post('/api/output-center/items/'+missing['record_id']+'/clear')
                self.assertEqual(cleared.status_code,200,cleared.text)
                self.assertEqual(cleared.json()['data']['updated_batches'][0]['summary']['total'],2)
                self.assertEqual(cleared.json()['data']['updated_batches'][0]['summary']['completed'],2)
                after = self.card(batch_id)
                self.assertEqual(after['summary']['total'],2)
                self.assertEqual(after['summary']['completed'],2)
                for child in after['items']:
                    self.assertEqual(hashlib.sha256(Path(child['output_path']).read_bytes()).hexdigest(),child['output_sha256'])
                    self.assertEqual(self.client.get('/api/result-assets/'+child['result_id']).status_code,200)
                    self.remove_test_file(child)
                self.cleanup('current','missing')
                self.assertNotIn(batch_id,[x['id'] for x in self.page()['items']])
                # Frozen batch API still returns original three nine-field identities.
                route='image-compression' if feature=='compression' else 'batch-watermark'
                durable=self.client.get(f'/api/{route}/batches/{batch_id}').json()['data']['items']
                self.assertEqual(len(durable),3)
                self.assertEqual({i['result_id'] for i in durable},{i['result_id'] for i in before['items']})
                self.restart()
                self.assertNotIn(batch_id,[x['id'] for x in self.page()['items']])

    def test_current_and_history_cleanup_are_disjoint_and_persist(self):
        historic=self.watermark()['batch_id']
        self.restart()
        current=self.watermark()['batch_id']
        old=self.card(historic);new=self.card(current)
        self.assertEqual([i['id'] for i in self.page('history')['items']],[historic])
        self.assertEqual([i['id'] for i in self.page('current')['items']],[current])
        self.remove_test_file(old['items'][0]);self.remove_test_file(new['items'][0])
        self.cleanup('current','missing')
        self.assertEqual(len(self.card(current)['items']),2)
        self.assertEqual(len(self.card(historic)['items']),3)
        self.cleanup('history','missing')
        self.assertEqual(len(self.card(historic)['items']),2)
        hashes={i['output_path']:i['output_sha256'] for c in (self.card(historic),self.card(current)) for i in c['items']}
        self.cleanup('current','all')
        self.assertEqual([i['id'] for i in self.page()['items']],[historic])
        self.restart()
        self.assertEqual([i['id'] for i in self.page()['items']],[historic])
        self.cleanup('history','all')
        self.restart()
        self.assertEqual(self.page()['total_count'],0)
        self.assertEqual(hashes,{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in hashes})

    def test_preview_failure_and_sha_mismatch_are_not_missing_files(self):
        batch_id=self.watermark()['batch_id'];before=self.card(batch_id)
        path=Path(before['items'][0]['output_path'])
        path.write_bytes(path.read_bytes()+b'owned mismatch')
        self.cleanup('current','missing')
        card=self.card(batch_id)
        self.assertEqual(len(card['items']),3)
        self.assertNotEqual(card['items'][0]['file_status'],'MISSING')
        self.assertFalse(card['items'][0]['available'])

    def test_invalid_bulk_scope_and_unknown_record_are_rejected(self):
        self.assertEqual(self.client.post('/api/output-center/cleanup',json={'scope':'all','mode':'all'}).status_code,422)
        self.assertEqual(self.client.post('/api/output-center/cleanup',json={'scope':'history','mode':'delete-files'}).status_code,422)
        batch_id=self.watermark()['batch_id']
        self.assertEqual(self.client.post('/api/output-center/items/not-an-id/clear').status_code,404)
        self.assertEqual(self.page()['items'][0]['id'],batch_id)

    def test_removed_batch_does_not_claim_new_result_reusing_a_missing_path(self):
        old_id=self.watermark()['batch_id'];before=self.card(old_id)
        self.remove_test_file(before['items'][0])
        self.assertEqual(self.client.post('/api/output-center/items/'+old_id+'/clear').status_code,200)
        new_id=self.watermark()['batch_id'];after=self.card(new_id)
        self.assertEqual(len(self.page()['items']),1)
        self.assertEqual(len(after['items']),3)
        self.assertTrue(all(item['available'] for item in after['items']))
        self.assertEqual(before['items'][0]['output_path'],after['items'][0]['output_path'])
        self.assertNotEqual(before['items'][0]['task_id'],after['items'][0]['task_id'])
        self.assertNotEqual(before['items'][0]['result_id'],after['items'][0]['result_id'])
        self.restart()
        self.assertTrue(all(item['available'] for item in self.card(new_id)['items']))


from tests.image_compression_ui import test_output_center_api as api_contract
from unittest.mock import patch
from PIL import Image
import copy


class SingleOutputCleanupTests(unittest.TestCase):
    setUp = api_contract.OutputCenterApiTests.setUp
    tearDown = api_contract.OutputCenterApiTests.tearDown

    def test_missing_single_removal_does_not_hide_a_new_explicit_result_at_same_path(self):
        old = self.shared_registry['retouch_task_001']
        old['output_sha256'] = hashlib.sha256(self.paths['retouch'].read_bytes()).hexdigest()
        card = next(i for i in self.client.get('/api/output-center/items').json()['data']['items'] if i['result_id']=='retouch_result_001')
        self.paths['retouch'].unlink()
        self.assertEqual(self.client.post('/api/output-center/items/'+card['id']+'/clear').status_code,200)
        Image.new('RGB',(92,60),(150,100,90)).save(self.paths['retouch'])
        record = copy.deepcopy(old)
        record.update(task_id='new-task',result_id='new-result',output_sha256=hashlib.sha256(self.paths['retouch'].read_bytes()).hexdigest())
        record['result'].update(task_id='new-task',result_id='new-result')
        self.shared_registry['new-task']=record
        after=next(i for i in self.client.get('/api/output-center/items').json()['data']['items'] if i['id']==card['id'])
        self.assertEqual(after['task_id'],'new-task')
        self.assertEqual(after['result_id'],'new-result')
        self.assertTrue(after['available'])

    def test_single_missing_scopes_keep_preview_failures_and_other_files(self):
        existing = self.shared_registry['retouch_task_001']
        existing['output_sha256'] = hashlib.sha256(self.paths['retouch'].read_bytes()).hexdigest()
        path = self.paths['retouch'].with_name('current-cleanup.png')
        path.write_bytes(self.paths['retouch'].read_bytes())
        current = copy.deepcopy(existing)
        current.update(task_id='current-task',result_id='current-result',output_path=path,result_file=str(path))
        current['result'].update(task_id='current-task',result_id='current-result',output_path=str(path),result_file=str(path))
        self.shared_registry['current-task'] = current
        self.paths['retouch'].unlink();path.unlink()
        # A real file whose preview exceeds the guard must not be called missing.
        with patch.object(Image,'MAX_IMAGE_PIXELS',1000):
            data=self.client.get('/api/output-center/items').json()['data']
            real=next(i for i in data['items'] if i['file_name']=='standard.png')
            self.assertEqual(self.client.get(real['thumbnail_url']).status_code,422)
            response=self.client.post('/api/output-center/cleanup',json={'scope':'current','mode':'missing'})
            self.assertEqual(response.status_code,200,response.text)
        after=self.client.get('/api/output-center/items').json()['data']
        self.assertNotIn('current-result',[i['result_id'] for i in after['items']])
        self.assertIn('retouch_result_001',[i['result_id'] for i in after['items']])
        self.assertIn(real['id'],[i['id'] for i in after['items']])
        self.client.post('/api/output-center/cleanup',json={'scope':'history','mode':'missing'})
        final=self.client.get('/api/output-center/items').json()['data']
        self.assertEqual(len(final['items']),4)
        self.assertTrue(self.paths['1080p'].is_file())
        self.assertTrue(self.paths['4k'].is_file())
        self.assertIn('current-task',self.shared_registry)  # Source/Task/Result provenance retained.


if __name__ == '__main__': unittest.main()
