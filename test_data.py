import json
import os
import shutil
import tempfile
import time
import unittest
from importlib.machinery import SourceFileLoader


HUD = SourceFileLoader('cc_hud_data_tests', 'cc-hud.pyw').load_module()


class DataLayerTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='cc-hud-test-')

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    @staticmethod
    def line(tokens, mid='message-1'):
        return json.dumps({
            'timestamp': '2026-10-10T00:00:00.000Z',
            'message': {'id': mid, 'model': 'test-model',
                        'usage': {'input_tokens': tokens, 'output_tokens': 1}},
        }) + '\n'

    def test_duplicate_message_uses_last_complete_usage(self):
        path = os.path.join(self.root, 'session.jsonl')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(self.line(2))
            fh.write(self.line(9))
        rows = HUD._parse_transcript(path)
        self.assertEqual(rows['message-1'][2], 9)

    def test_cache_invalidates_on_nanosecond_change(self):
        path = os.path.join(self.root, 'session.jsonl')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(self.line(1))
        now = time.time_ns()
        os.utime(path, ns=(now, now))
        first = HUD.haha_days(self.root)[0]
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(self.line(9))
        os.utime(path, ns=(now + 1000, now + 1000))
        second = HUD.haha_days(self.root)[0]
        self.assertEqual(first['2026-10-10']['in'], 1)
        self.assertEqual(second['2026-10-10']['in'], 9)

    def test_export_url_redaction_removes_query_and_credentials(self):
        value = HUD.redact_url('https://user:secret@example.test/v1?key=abc#frag')
        self.assertEqual(value, 'https://example.test/v1')
        value = HUD._redact_export({'error': 'Bearer abc123',
                                    'eps': [('p', 'claude', 'https://x.test/?token=abc')]})
        text = json.dumps(value, ensure_ascii=False)
        self.assertNotIn('abc123', text)
        self.assertNotIn('token=abc', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
