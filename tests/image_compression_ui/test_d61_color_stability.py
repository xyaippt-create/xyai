"""D61 color product contracts; real processor and isolated existing registry."""
import hashlib
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from tests.image_compression_ui import test_reference_color_api as reference_tests


class D61ColorOutputTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.image_compression_api import register_image_compression_routes
        from engine.storage.shared_task_registry import SharedTaskRegistry
        from main import DEFAULT_TMP_DIR_NAME
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.formal = self.root / 'formal'
        self.cache = self.formal / DEFAULT_TMP_DIR_NAME
        self.cache.mkdir(parents=True)
        self.now = 1_800_000_000.0
        self.events = []
        self.registry = SharedTaskRegistry(self.formal)
        app = FastAPI()
        self.state = register_image_compression_routes(
            app, user_dirs_provider=lambda: {'app_data_root':self.formal, 'normal_output_dir':self.formal/'输出/1080P画质', 'tmp_dir':self.cache},
            shared_task_registry=self.registry, now_provider=lambda:self.now,
            output_settings_provider=lambda:{'built_in_default_root':str(self.formal/'输出'), 'saved_default_root':str(self.formal/'输出')},
            output_dir_validator=lambda value:{'valid':True,'writable':True,'normalized_path':str(Path(value).resolve())},
            folder_opener=lambda value:None,
            runtime_event_logger=lambda event,**fields:self.events.append({'event':event,**fields}),
        )
        self.client = TestClient(app)
    tearDown = reference_tests.ReferenceColorApiTests.tearDown
    intake = reference_tests.ReferenceColorApiTests.intake
    def fixture_intake(self, name):
        path = Path(__file__).resolve().parents[2] / 'output/evaluation/d01_color_decision_20260812/inputs' / name
        response = self.client.post('/api/image-compression/intake', files={'file': (name, path.read_bytes(), 'image/png')})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['data']

    def test_d61_no_output_is_not_success(self):
        target = self.intake(flat=128)
        for endpoint, payload in (
            ('/api/color-correction/run', {'source_token': target['source_token']}),
            ('/api/color-correction/reference-run', {'target_source_token': target['source_token'], 'reference_source_token': target['source_token']}),
        ):
            response = self.client.post(endpoint, json=payload)
            data = response.json()['data']
            self.assertFalse(response.json()['success'])
            self.assertEqual(data['task']['status'], 'failed')
            self.assertIsNone(data['result'])
            self.assertFalse(data['task']['result_id'])
            self.assertTrue(data['task']['failure_reason'])
            self.assertEqual(self.registry[data['task']['task_id']]['status'], 'failed')

    def test_d61_completed_requires_persisted_decodable_result(self):
        target = self.fixture_intake('D01_02.png')
        response = self.client.post('/api/color-correction/run', json={'source_token': target['source_token']})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()['data']
        self.assertEqual(data['task']['status'], 'completed')
        result = data['result']
        output = Path(result['output_path'])
        self.assertGreater(output.stat().st_size, 0)
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), result['output_sha256'])
        from PIL import Image
        with Image.open(output) as image:
            image.load()
            self.assertEqual(image.size, (result['width'], result['height']))
        persisted = json.loads(self.registry.path.read_text(encoding='utf8'))['records'][data['task']['task_id']]
        self.assertEqual(persisted['result_id'], result['result_id'])
        items = self.client.get('/api/output-center/items').json()['data']['items']
        self.assertTrue(any(x.get('result_id') == result['result_id'] for x in items))

    def test_d61_registration_failure_never_leaves_completed_task(self):
        target = self.fixture_intake('D01_02.png')
        original = self.registry._commit
        def reject_completed(records):
            if any(r.get('task_family') == 'color_correction' and r.get('status') == 'completed' for r in records.values()):
                raise OSError('D61 injected registry write failure')
            return original(records)
        with patch.object(self.registry, '_commit', side_effect=reject_completed):
            response = self.client.post('/api/color-correction/run', json={'source_token': target['source_token']})
        data = response.json()['data']
        self.assertFalse(response.json()['success'])
        self.assertEqual(data['task']['status'], 'failed')
        self.assertIsNone(data['result'])
        self.assertFalse(data['task']['result_id'])
        self.assertFalse(data['task']['result_file'])
        self.assertEqual(self.registry[data['task']['task_id']]['status'], 'failed')
