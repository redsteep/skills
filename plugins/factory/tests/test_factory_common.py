"""Secrets from the repo's .env: only the factory's own keys, never overriding the environment."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from factory_common import load_repo_secrets  # noqa: E402

ENV = """# comment
export TRELLO_API_KEY="key-from-dotenv"
TRELLO_TOKEN='token-from-dotenv'
OPENAI_API_KEY=must-not-leak
"""


class RepoSecrets(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="factory-secrets-"))
        (self.repo / ".env").write_text(ENV)

    def test_only_the_factory_keys_are_read_unquoted(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            load_repo_secrets(self.repo)
            self.assertEqual({k: os.environ[k] for k in os.environ},
                             {"TRELLO_API_KEY": "key-from-dotenv", "TRELLO_TOKEN": "token-from-dotenv"})

    def test_a_key_already_in_the_environment_wins(self):
        with mock.patch.dict(os.environ, {"TRELLO_TOKEN": "from-systemd"}, clear=True):
            load_repo_secrets(self.repo)
            self.assertEqual(os.environ["TRELLO_TOKEN"], "from-systemd")


if __name__ == "__main__":
    unittest.main()
