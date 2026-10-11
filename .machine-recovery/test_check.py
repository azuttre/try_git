"""Hermetic contract tests for the portable recovery gate (stdlib only)."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

_folder = Path(__file__).resolve().parent
_source = _folder / ('check.py' if (_folder / 'check.py').exists() else 'machine_recovery_gate.py')
_spec = importlib.util.spec_from_file_location('portable_recovery_gate', _source)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


class RecoveryGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.write('restore.md', 'baseline restore\n')
        self.write(gate.POLICY, json.dumps({'schema_version':1, 'repository':'owner/repo',
                   'owned_records':['restore.md'], 'generated_paths':['data/']}))
        self.git('add', '.'); self.git('commit', '-qm', 'baseline')
        self.base = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root).decode()

    def write(self, path, text):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)

    def change(self, path='code.py'):
        self.write(path, 'replacement requirement\n')
        self.git('add', '.'); self.git('commit', '-qm', 'change')

    def receipt(self, mode='not-applicable', reason=None):
        policy, paths, digest, _, changed, baseline = gate.inspect(self.root, self.base)
        value = {'repository':'owner/repo', 'diff_sha256':digest, 'disposition':mode,
                 'reason':reason or 'Only presentation changed; installation, state and recovery remain identical.',
                 'owned_records':['restore.md'] if mode == 'updated' else []}
        self.write(gate.CHANGES + 'change.json', json.dumps(value))
        self.git('add', '.'); self.git('commit', '-qm', 'disposition')
        return value

    def check(self):
        policy, paths, digest, receipts, changed, baseline = gate.inspect(self.root, self.base)
        return gate.validate_receipt(policy, paths, digest, receipts, changed)

    def test_source_change_without_disposition_blocks(self):
        self.change()
        with self.assertRaisesRegex(ValueError, 'one recovery disposition'):
            self.check()

    def test_exact_not_applicable_and_receipt_self_exclusion(self):
        self.change(); value = self.receipt()
        self.assertEqual(self.check(), value)

    def test_later_source_change_invalidates_receipt(self):
        self.change(); self.receipt(); self.change('more.py')
        with self.assertRaises(ValueError): self.check()

    def test_updated_requires_changed_authoritative_record(self):
        self.change(); self.receipt('updated')
        with self.assertRaisesRegex(ValueError, 'authoritative'): self.check()

    def test_updated_with_owned_record_passes(self):
        self.change('restore.md'); self.receipt('updated')
        self.assertEqual(self.check()['disposition'], 'updated')

    def test_vague_waiver_and_duplicate_receipt_block(self):
        self.change(); self.receipt(reason='N/A')
        with self.assertRaisesRegex(ValueError, 'explanation'): self.check()
        self.receipt()
        self.write(gate.CHANGES + 'duplicate.json', (self.root / (gate.CHANGES + 'change.json')).read_text())
        self.git('add', '.'); self.git('commit', '-qm', 'duplicate')
        with self.assertRaisesRegex(ValueError, 'one recovery disposition'): self.check()

    def test_generated_data_only_needs_no_disposition(self):
        self.change('data/history.csv')
        self.assertIsNone(self.check())

    def test_exemption_widening_cannot_hide_own_change(self):
        self.change()
        p = json.loads((self.root / gate.POLICY).read_text())
        p['generated_paths'] = ['']
        self.write(gate.POLICY, json.dumps(p)); self.git('add', '.'); self.git('commit', '-qm', 'invalid policy')
        with self.assertRaisesRegex(ValueError, 'generated-path'): self.check()
        p['generated_paths'] = ['code.py']
        self.write(gate.POLICY, json.dumps(p)); self.git('add', '.'); self.git('commit', '-qm', 'widen')
        self.assertIn('code.py', gate.inspect(self.root, self.base)[1])

    def test_staged_ignores_unstaged_receipt_and_source(self):
        self.change(); self.receipt()
        expected = gate.inspect(self.root, self.base)
        self.write('code.py', 'unstaged\n')
        self.write(gate.CHANGES + 'change.json', '{}')
        observed = gate.inspect(self.root, self.base, staged=True)
        self.assertEqual(expected[1:4], observed[1:4])

    def test_deleted_owner_record_and_policy_block(self):
        (self.root / 'restore.md').unlink(); self.git('add', '-u'); self.git('commit', '-qm', 'delete owner')
        with self.assertRaisesRegex(ValueError, 'missing authoritative'): self.check()
        (self.root / gate.POLICY).unlink(); self.git('add', '-u'); self.git('commit', '-qm', 'delete policy')
        with self.assertRaises(subprocess.CalledProcessError): self.check()

    def test_digest_independent_of_local_diff_configuration(self):
        self.change(); expected = gate.inspect(self.root, self.base)[1:3]
        for key, value in [('diff.context','100'),('core.abbrev','7'),('diff.renames','true')]:
            self.git('config',key,value)
            self.assertEqual(gate.inspect(self.root,self.base)[1:3],expected)

    def test_rename_and_mode_change_are_visible(self):
        self.git('mv','restore.md','renamed.md')
        self.git('update-index','--chmod=+x','renamed.md')
        before, after = gate.tree(self.root,self.base),gate.tree(self.root,'')
        paths, _ = gate.change_digest(before,after,{'generated_paths':[]})
        self.assertEqual(paths,['renamed.md','restore.md'])

    def test_bootstrap_and_composed_existing_evidence_have_no_cycle(self):
        # Start from the commit before this policy existed, as rollout PRs do.
        self.git('rm',gate.POLICY);self.git('commit','-qm','remove for fixture')
        base=self.git('rev-parse','HEAD').strip()
        p={'schema_version':1,'repository':'owner/repo','owned_records':['new-guide.md'],
           'generated_paths':[],'evidence_paths':['other-assessment/']}
        self.write(gate.POLICY,json.dumps(p));self.write('new-guide.md','new restore guide\n')
        self.write('other-assessment/record.json','first attestation\n')
        self.git('add','.');self.git('commit','-qm','bootstrap')
        first=gate.inspect(self.root,base)[1:3]
        self.write('other-assessment/record.json','bound final attestation\n')
        self.git('add','.');self.git('commit','-qm','assessment')
        self.assertEqual(gate.inspect(self.root,base)[1:3],first)


if __name__ == '__main__':
    unittest.main()
