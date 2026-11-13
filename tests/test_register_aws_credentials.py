"""Offline playbook tests with dummy credentials and a fake kubectl API boundary."""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
PLAYBOOK = REPO / "playbooks" / "operations" / "register-aws-credentials.yml"
ACCESS = "AKIA" + "A" * 16
SECRET = "a" * 40


class RegistrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eso-ansible-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inventory = self.root / "inventory.ini"
        self.inventory.write_text(
            "[kube_control_plane]\n"
            "test-cp ansible_connection=local\n"
        )
        self.credentials = self.root / "credentials"
        self.write_credentials()
        self.state = self.root / "state.json"
        self.calls = self.root / "calls.jsonl"
        self.kubectl = self.root / "kubectl"
        self.kubectl.write_text('''#!/usr/bin/env python3
import json, pathlib, sys
root = pathlib.Path(__file__).parent
args = sys.argv[1:]
with (root / 'calls.jsonl').open('a') as log:
    log.write(json.dumps(args) + '\\n')
assert '--kubeconfig' in args
state = root / 'state.json'
if 'get' in args and 'secret' in args:
    if state.exists():
        print(state.read_text())
elif 'apply' in args:
    assert '--server-side' in args
    assert '--field-manager=manual-aws-credentials' in args
    if (root / 'reject-apply').exists():
        sys.stderr.write('simulated conflict: ' + sys.stdin.read())
        sys.exit(1)
    document = json.load(sys.stdin)
    assert document['metadata'] == {'name': 'aws-ssm-credentials', 'namespace': 'external-secrets'}
    assert document['type'] == 'Opaque'
    state.write_text(json.dumps(document))
    print('secret/aws-ssm-credentials')
else:
    sys.exit('Unexpected kubectl invocation')
''')
        self.kubectl.chmod(0o700)

    def write_credentials(self, secret=SECRET):
        self.credentials.write_text(
            f"[homelab-eso]\naws_access_key_id={ACCESS}\naws_secret_access_key={secret}\n"
        )
        self.credentials.chmod(0o600)

    def run_playbook(self, *options):
        env = os.environ.copy()
        env['ANSIBLE_LOCAL_TEMP'] = str(self.root / 'ansible-local')
        env['ANSIBLE_NOCOLOR'] = '1'
        env['ANSIBLE_DEBUG'] = '0'
        env['AWS_ACCESS_KEY_ID'] = 'ignored-environment-value'
        result = subprocess.run([
            'ansible-playbook', '-i', str(self.inventory), str(PLAYBOOK),
            '-e', json.dumps({
                'ansible_become': False,
                'ansible_python_interpreter': sys.executable,
                'aws_credentials_file': str(self.credentials),
                'kubeconfig_file': str(self.root / 'dummy-kubeconfig'),
                'kubectl_binary': str(self.kubectl),
                'ansible_remote_tmp': str(self.root / 'ansible-remote'),
            }), *options,
        ], cwd=REPO, env=env, capture_output=True, text=True)
        output = result.stdout + result.stderr
        for secret in (ACCESS, SECRET, 'b' * 40):
            self.assertNotIn(secret, output)
            self.assertNotIn(base64.b64encode(secret.encode()).decode(), output)
        if self.calls.exists():
            calls = self.calls.read_text()
            self.assertNotIn(ACCESS, calls)
            self.assertNotIn(SECRET, calls)
        return result, output

    def assert_success(self, *options):
        result, output = self.run_playbook(*options)
        self.assertEqual(result.returncode, 0, output)
        return output

    def apply_count(self):
        return sum('apply' in json.loads(line) for line in self.calls.read_text().splitlines())

    def test_check_create_repeat_rotate(self):
        output = self.assert_success('--check', '--diff')
        self.assertIn('would be created/updated', output)
        self.assertFalse(self.state.exists())
        self.assertEqual(self.apply_count(), 0)
        self.assert_success('--diff', '-v')
        state = json.loads(self.state.read_text())
        self.assertEqual(base64.b64decode(state['data']['secret-access-key']).decode(), SECRET)
        self.assertEqual(self.apply_count(), 1)
        self.assertIn('already matches', self.assert_success())
        self.assertEqual(self.apply_count(), 1)
        self.write_credentials('b' * 40)
        self.assert_success()
        self.assertEqual(self.apply_count(), 2)
        state = json.loads(self.state.read_text())
        self.assertEqual(base64.b64decode(state['data']['secret-access-key']).decode(), 'b' * 40)

    def test_missing_credentials_file_fails_before_api_call(self):
        self.credentials.unlink()
        result, _ = self.run_playbook()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_missing_profile_does_not_use_environment_credentials(self):
        self.credentials.write_text('[other]\n')
        result, _ = self.run_playbook()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.state.exists())

    def test_session_credentials_fail_before_api_call(self):
        with self.credentials.open('a') as credentials:
            credentials.write('aws_session_token=temporary-token\n')
        result, _ = self.run_playbook()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_api_error_does_not_expose_stdin_secret(self):
        (self.root / 'reject-apply').touch()
        result, _ = self.run_playbook('--diff', '-vvv')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.state.exists())


if __name__ == '__main__':
    unittest.main()
