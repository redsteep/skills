"""factory-attach puts the approved brief on the card. Two promises: an amended brief replaces
the earlier upload instead of sitting beside it, and `.env` wins over a worker's environment —
the daemon's, where a rotated Trello token stays stale (the old MCP server's 401s)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from factory_attach import attach  # noqa: E402
from factory_common import load_repo_secrets  # noqa: E402


class Attach(unittest.TestCase):
    def test_an_earlier_upload_of_the_same_name_is_replaced(self):
        calls = []

        def call(method, path, body=None, content_type=None):
            calls.append((method, path))
            if method == "GET":
                return [{"id": "a1", "name": "card-brief.md"}, {"id": "a2", "name": "mockup.png"}]
            if method == "POST":
                self.assertIn(b"# Brief", body)
                return {"url": "https://trello.com/new"}

        url = attach("c9", "card-brief.md", b"# Brief\n", call)
        self.assertEqual(url, "https://trello.com/new")
        self.assertEqual(calls, [("GET", "cards/c9/attachments"),
                                 ("DELETE", "cards/c9/attachments/a1"),
                                 ("POST", "cards/c9/attachments")])


class Secrets(unittest.TestCase):
    def test_override_takes_the_env_file_over_a_stale_environment(self):
        with tempfile.TemporaryDirectory() as repo:
            Path(repo, ".env").write_text("TRELLO_TOKEN=fresh\nOTHER=x\n")
            old = os.environ.get("TRELLO_TOKEN")
            try:
                os.environ["TRELLO_TOKEN"] = "stale"
                load_repo_secrets(Path(repo))
                self.assertEqual(os.environ["TRELLO_TOKEN"], "stale")
                load_repo_secrets(Path(repo), override=True)
                self.assertEqual(os.environ["TRELLO_TOKEN"], "fresh")
                self.assertNotIn("OTHER", os.environ)
            finally:
                if old is None:
                    os.environ.pop("TRELLO_TOKEN", None)
                else:
                    os.environ["TRELLO_TOKEN"] = old


if __name__ == "__main__":
    unittest.main()
