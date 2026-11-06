#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
FIXTURES = SOURCE / "shared/fixtures"
sys.path.insert(0, str(FIXTURES))
from normalize import normalize


class StateTests(unittest.TestCase):
    def test_shared_fixtures(self):
        with tempfile.TemporaryDirectory(prefix="jj-state-") as tmp:
            config = Path(tmp) / "jj.toml"
            config.write_text('user.name="Test"\nuser.email="test@example.invalid"\n')
            os.environ["JJ_CONFIG"] = str(config)
            for expected in sorted((FIXTURES / "expected").glob("*.txt")):
                with self.subTest(case=expected.stem):
                    root = Path(tmp).resolve() / (expected.stem + " with spaces")
                    subprocess.run(["bash", str(FIXTURES / "setup.sh"), expected.stem, str(root)], check=True)
                    result = subprocess.run(
                        ["/bin/bash", "-c", '. "$1"; read_jj_state "$2"', "bash",
                         str(SOURCE / "plugins/jj-agent/scripts/state.sh"), str(root)],
                        check=True, capture_output=True, text=True,
                    )
                    self.assertEqual(result.stderr, "")
                    self.assertEqual(normalize(result.stdout, root), expected.read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
