"""Result identity survives persisted listing removal facts and Registry reload."""
import hashlib
import unittest
from pathlib import Path
from tests.image_compression_ui import test_output_center_cleanup as cleanup


class SamePathRebindTests(unittest.TestCase):
    setUp = cleanup.OutputCenterCleanupTests.setUp
    tearDown = cleanup.OutputCenterCleanupTests.tearDown
    restart = cleanup.OutputCenterCleanupTests.restart
    watermark = cleanup.OutputCenterCleanupTests.watermark
    compression = cleanup.OutputCenterCleanupTests.compression
    wait_batch = cleanup.OutputCenterCleanupTests.wait_batch

    def page(self):
        return self.client.get('/api/output-center/items').json()['data']

    def single(self, parent=None, name='same-path.png', fail=False):
        from tests.image_compression_ui.test_batch_output_contract import source_bytes
        response = self.client.post('/api/image-compression/intake-result',json={'result_id':parent}) if parent else self.client.post('/api/image-compression/intake',files={'file':(name,source_bytes(),'image/png')})
        self.assertEqual(response.status_code,200,response.text)
        response=self.client.post('/api/image-compression/run',json={'source_token':response.json()['data']['source_token'],
            'operation_mode':'UPLOAD_ADAPTATION' if fail else ('RESIZE_REDUCTION' if parent else 'LOSSLESS_COMPRESSION'),'params':{'max_file_size_bytes':1} if fail else ({'target_short_side':80} if parent else {}),
            'current_task_output_root':str(self.runtime.formal_root/'输出/图片压缩')})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['data']['task']

    def stage_owned_old_bytes(self, item):
        record=self.client.app.state.task_registry[item['task_id']]
        path=Path(record['result_file']);held=path.with_name('owned-original-'+path.name)
        self.assertTrue(path.resolve().is_relative_to(self.runtime.formal_root.resolve()))
        before=hashlib.sha256(path.read_bytes()).hexdigest();path.rename(held)
        return path,held,before

    def test_real_single_new_result_and_parent_survive_refresh_reload_and_legacy_facts(self):
        parent=self.single(name='parent.png');old=self.single(parent['result_id'])
        card=next(c for c in self.page()['items'] if c.get('result_id')==old['result_id'])
        self.assertEqual(self.client.post('/api/output-center/items/'+card['id']+'/clear').status_code,200)
        path,held,sha=self.stage_owned_old_bytes(old);new=self.single(parent['result_id'])
        self.assertEqual(Path(self.client.app.state.task_registry[new['task_id']]['result_file']),path)
        self.assertNotEqual(old['result_id'],new['result_id'])
        for reload in (False,True,True):
            if reload:self.restart()
            rows=self.page()['items'];self.assertFalse(any(c.get('result_id')==old['result_id'] for c in rows))
            actual=next(c for c in rows if c['id']==card['id'])
            self.assertEqual((actual['task_id'],actual['result_id']),(new['task_id'],new['result_id']))
            self.assertTrue(actual['unified_result']);self.assertTrue(actual['continue_eligible'])
            if not reload:self.assertEqual(actual['list_scope'],'current')
            trace=self.client.get('/api/output-center/results/'+new['result_id']+'/lineage').json()['data']
            self.assertEqual(trace['items'][-1]['source_result_id'],parent['result_id'])
            intake=self.client.post('/api/image-compression/intake-result',json={'result_id':new['result_id']})
            self.assertEqual(intake.status_code,200,intake.text)
        self.assertEqual(hashlib.sha256(held.read_bytes()).hexdigest(),sha)
        self.assertEqual(self.client.app.state.task_registry['output_center_hidden:'+card['id']]['removed_result_id'],old['result_id'])

    def test_watermark_same_path_and_compression_reserved_path_keep_child_identity(self):
        from tests.image_compression_ui.test_batch_output_contract import source_bytes
        for feature in ('compression','watermark'):
            with self.subTest(feature=feature):
                create=lambda:self.wait_batch(self.compression([('files',(f'{feature}-{i}.png',source_bytes(),'image/png')) for i in range(3)])) if feature=='compression' else self.watermark()
                old=create();bid=old.get('batch_id') or old['batchId'];card=next(c for c in self.page()['items'] if c.get('batch_id')==bid)
                child=card['items'][0];self.assertEqual(self.client.post('/api/output-center/items/'+child['record_id']+'/clear').status_code,200)
                if feature=='compression':
                    # OC-03R1: repeat the same source/directory, retaining the old output.
                    # Persisted prepared paths remain reserved across Registry reloads.
                    path=Path(child['output_path']);held=path
                    sha=hashlib.sha256(path.read_bytes()).hexdigest()
                else:
                    path,held,sha=self.stage_owned_old_bytes(child)
                new=create();new_bid=new.get('batch_id') or new['batchId']
                self.restart();new_card=next(c for c in self.page()['items'] if c.get('batch_id')==new_bid)
                if feature=='compression':
                    # The frozen compressor correctly protects its prepared path reservation.
                    # A new final name is required; the occupied old name must not be reused.
                    chosen=new_card['items'][0]
                    self.assertNotEqual(Path(chosen['output_path']),path)
                    self.assertEqual(Path(chosen['output_path']).parent,path.parent)
                else:
                    chosen=next(c for c in new_card['items'] if Path(c['output_path'])==path)
                self.assertNotEqual(chosen['result_id'],child['result_id']);self.assertNotEqual(chosen['task_id'],child['task_id'])
                self.assertNotEqual(chosen['batch_item_id'],child['batch_item_id'])
                self.assertTrue(chosen['available'])
                self.assertEqual(self.client.post('/api/image-compression/intake-result',json={'result_id':chosen['result_id']}).json()['data']['source_task_id'],chosen['task_id'])
                remaining=next(c for c in self.page()['items'] if c.get('batch_id')==bid)
                self.assertEqual(len(remaining['items']),2)
                for item in remaining['items']:self.assertEqual(self.client.post('/api/output-center/items/'+item['record_id']+'/clear').status_code,200)
                self.restart();self.assertFalse(any(c.get('batch_id')==bid for c in self.page()['items']))
                self.assertEqual(hashlib.sha256(held.read_bytes()).hexdigest(),sha)

    def test_legacy_removal_without_result_identity_stays_hidden_and_failed_task_cannot_bind(self):
        old=self.single(name='legacy.png');card=next(c for c in self.page()['items'] if c.get('result_id')==old['result_id'])
        registry=self.client.app.state.task_registry
        registry['output_center_hidden:'+card['id']]={'record_kind':'output_center_hidden','item_id':card['id'],'output_path':str(registry[old['task_id']]['result_file'])}
        other=self.single(name='different.png');failed=self.single(other['result_id'],fail=True)
        self.assertEqual(failed['status'],'failed');self.assertFalse(failed.get('result_id'))
        self.restart();rows=self.page()['items'];self.assertFalse(any(c['id']==card['id'] for c in rows))
        actual=next(c for c in rows if c.get('result_id')==other['result_id']);self.assertEqual(actual['task_id'],other['task_id'])
        self.assertFalse(any(c.get('task_id')==failed['task_id'] for c in rows))
