import unittest
from fastapi.testclient import TestClient
from tests.support.app_runtime import isolated_app_runtime


class LineageFeedbackIsolationTests(unittest.TestCase):
    def test_explicit_branch_task_cannot_be_replaced_by_a_foreign_target(self):
        with isolated_app_runtime(self.id()) as runtime:
            with TestClient(runtime.main.build_web_app()) as client:
                response=client.post('/api/v1/feedback/context-snapshot',json={
                    'task_id':'branch-A','source_feature':'image_compression',
                    'feedback_target':{'feature_key':'image_compression','task_id':'branch-B'},
                })
                self.assertEqual(response.status_code,409,response.text)
