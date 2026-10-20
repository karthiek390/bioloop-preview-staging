"""Exercise monitor cleanup using real Linux processes and a fake Docker CLI."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from readiness import publish


@unittest.skipUnless(sys.platform.startswith('linux'), 'Requires Linux /proc process identity checks')
class LifecycleTests(unittest.TestCase):
    @contextmanager
    def session(self, expired=False):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            env = {**os.environ, 'PREVIEW_STATE_DIR': str(state),
                   'PREVIEW_SOURCE_DIR': str(state), 'GITHUB_REPOSITORY': 'IUSCA/bioloop',
                   'PREVIEW_PR': '42', 'PREVIEW_SHA': 'a' * 40,
                   'GITHUB_STEP_SUMMARY': str(state / 'summary.md')}
            data = publish(state / 'preview-ready.json', 'https://test-preview.trycloudflare.com', 30, env)
            if expired:
                for key in ('ready_at', 'expires_at'):
                    value = datetime.strptime(data[key], '%Y-%m-%dT%H:%M:%SZ') - timedelta(hours=1)
                    data[key] = value.strftime('%Y-%m-%dT%H:%M:%SZ')
                data['deadline_epoch'] -= 3600
                (state / 'preview-ready.json').write_text(json.dumps(data))
            (state / 'api.env').touch()
            shutil.copy2(shutil.which('sleep'), state / 'cloudflared')
            tunnel = subprocess.Popen([str(state / 'cloudflared'), '300'],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            (state / 'tunnel.pid').write_text(str(tunnel.pid))
            binary = state / 'bin'
            binary.mkdir()
            docker = binary / 'docker'
            docker.write_text(f'#!{sys.executable}\n' + '''
import os, sys
from pathlib import Path
state = Path(os.environ['PREVIEW_STATE_DIR'])
if sys.argv[1] == 'inspect':
    (state / 'polled').touch()
    print('running healthy')
elif 'down' in sys.argv:
    (state / 'teardown').touch()
elif '-q' in sys.argv and 'ps' in sys.argv:
    print('fake-preview-container')
''')
            docker.chmod(0o755)
            env['PATH'] = str(binary) + os.pathsep + env['PATH']
            try:
                yield state, env, tunnel
            finally:
                if tunnel.poll() is None:
                    tunnel.terminate()
                tunnel.wait(timeout=5)

    def run_wait(self, env):
        return subprocess.run(['bash', str(Path(__file__).with_name('run.sh')), 'wait'],
                              env=env, capture_output=True, text=True, timeout=20)

    def test_expiration_stops_tunnel_and_requests_stack_teardown(self):
        with self.session(expired=True) as (state, env, tunnel):
            result = self.run_wait(env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((state / 'teardown').exists())
            self.assertFalse((state / 'tunnel.pid').exists())
            tunnel.wait(timeout=5)

    def test_dead_tunnel_fails_and_still_requests_teardown(self):
        with self.session() as (state, env, tunnel):
            tunnel.terminate()
            tunnel.wait(timeout=5)
            result = self.run_wait(env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Tunnel stopped early', result.stderr)
            self.assertTrue((state / 'teardown').exists())

    def test_cancellation_while_monitoring_cleans_up(self):
        with self.session() as (state, env, tunnel):
            process = subprocess.Popen(['bash', str(Path(__file__).with_name('run.sh')), 'wait'],
                                       env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, start_new_session=True)
            try:
                limit = time.monotonic() + 8
                while not (state / 'polled').exists() and time.monotonic() < limit:
                    time.sleep(0.05)
                self.assertTrue((state / 'polled').exists(), 'Monitor did not reach service checks')
                os.killpg(process.pid, signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=20)
                self.assertNotEqual(process.returncode, 0, stdout + stderr)
                self.assertTrue((state / 'teardown').exists(), stdout + stderr)
                self.assertFalse((state / 'tunnel.pid').exists())
                tunnel.wait(timeout=5)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
