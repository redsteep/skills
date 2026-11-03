"""factory-download fetches a card's uploaded files for a worker to read; links stay links."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from factory_download import download  # noqa: E402


class Download(unittest.TestCase):
    def test_uploads_are_saved_and_links_listed(self):
        attachments = [
            {"id": "6ae9aaaa000001", "isUpload": True, "fileName": "Skärmbild 1.png",
             "url": "https://trello.com/1/cards/c9/attachments/1/download/x.png"},
            {"id": "6ae9aaaa000002", "isUpload": False, "url": "https://github.com/o/r/pull/5"},
        ]
        got = []
        with tempfile.TemporaryDirectory() as d:
            lines = download("c9", Path(d), call=lambda method, path: attachments,
                             get=lambda url: got.append(url) or b"PNG")
            saved = Path(d) / "000001-Skärmbild_1.png"
            self.assertEqual(lines, [str(saved), "link https://github.com/o/r/pull/5"])
            self.assertEqual(saved.read_bytes(), b"PNG")
        self.assertEqual(got, ["https://trello.com/1/cards/c9/attachments/1/download/x.png"])


if __name__ == "__main__":
    unittest.main()
