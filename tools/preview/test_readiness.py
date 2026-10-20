"""Validate the public handoff used between preview startup and monitoring."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('readiness', Path(__file__).with_name('readiness.py'))
readiness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readiness)

ENV = {'GITHUB_REPOSITORY': 'IUSCA/bioloop', 'PREVIEW_PR': '42',
       'PREVIEW_SHA': 'a' * 40, 'GH_TOKEN': 'must-not-be-published'}
URL = 'https://sample-preview.trycloudflare.com'


class ReadinessTests(unittest.TestCase):
    def make(self, path):
        return readiness.publish(path, URL, 30, ENV)

    def test_only_public_fields_are_published_and_survive_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'preview-ready.json'
            data = self.make(path)
            self.assertEqual(readiness.validate(json.loads(path.read_text()), ENV), data)
            self.assertEqual(set(data), readiness.FIELDS)
            self.assertNotIn(ENV['GH_TOKEN'], path.read_text())
            if os.name == 'posix':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_rejects_unsafe_urls_before_writing_any_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'preview-ready.json'
            for url in ('http://sample.trycloudflare.com', 'https://evil.example',
                        URL + '/?token=secret', URL + '.evil.example'):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    readiness.publish(path, url, 30, ENV)
            self.assertFalse(path.exists())

    def test_rejects_another_runs_context(self):
        with tempfile.TemporaryDirectory() as directory:
            data = self.make(Path(directory) / 'preview-ready.json')
            for key, value in (('PREVIEW_SHA', 'b' * 40), ('PREVIEW_PR', '43'),
                               ('GITHUB_REPOSITORY', 'other/repo')):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    readiness.validate(data, {**ENV, key: value})

    def test_rejects_tampered_deadline_or_extra_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            data = self.make(Path(directory) / 'preview-ready.json')
            for changes in ({'deadline_epoch': data['deadline_epoch'] + 60},
                            {'duration_minutes': 120}, {'secret': 'unexpected'}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    readiness.validate({**data, **changes}, ENV)

    def test_rejects_unsupported_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                readiness.publish(Path(directory) / 'preview-ready.json', URL, 5, ENV)


if __name__ == '__main__':
    unittest.main()
