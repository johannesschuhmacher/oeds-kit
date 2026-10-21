"""Regression checks for operations that can overwrite a checkout."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/assemble_workspace.py'


class AssemblySafetyTest(unittest.TestCase):
    def test_dry_run_never_removes_existing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            sentinel = Path(temp) / 'keep.txt'
            sentinel.write_text('keep')
            result = subprocess.run([sys.executable, str(SCRIPT), '--output', temp,
                                     '--clean', '--dry-run'], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sentinel.read_text(), 'keep')

    def test_refuse_replacing_deployment_checkout(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--output',
                                 str(SCRIPT.parents[1]), '--clean'], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'outside the deployment checkout', result.stderr)

    def test_nonempty_output_requires_explicit_clean(self):
        with tempfile.TemporaryDirectory() as temp:
            sentinel = Path(temp) / 'keep.txt'
            sentinel.write_text('keep')
            result = subprocess.run([sys.executable, str(SCRIPT), '--output', temp],
                                    capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertTrue(sentinel.exists())


if __name__ == '__main__':
    unittest.main()
