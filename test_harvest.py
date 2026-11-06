import io
import json
import unittest
from unittest.mock import patch

import harvest


class PageSelectionTest(unittest.TestCase):
    def select(self, targets):
        with patch("harvest.urllib.request.urlopen", return_value=io.StringIO(json.dumps(targets))):
            return harvest.page_ws()

    def test_skips_other_sites_and_non_page_targets(self):
        targets = [
            {"type": "page", "url": "https://www.douyin.com/", "webSocketDebuggerUrl": "wrong"},
            {"type": "service_worker", "url": "https://www.xiaohongshu.com/", "webSocketDebuggerUrl": "worker"},
            {"type": "page", "url": "https://www.xiaohongshu.com/user/profile/example", "webSocketDebuggerUrl": "right"},
        ]
        self.assertEqual(self.select(targets), "right")

    def test_missing_rednote_fails_without_fallback(self):
        for url in ("https://www.douyin.com/", "https://www.xiaohongshu.com.evil.test/", "about:blank"):
            with self.subTest(url=url), self.assertRaisesRegex(SystemExit, "没有小红书"):
                self.select([{"type": "page", "url": url, "webSocketDebuggerUrl": "wrong"}])

    def test_bare_domain(self):
        self.assertEqual(self.select([{"type": "page", "url": "https://xiaohongshu.com/", "webSocketDebuggerUrl": "right"}]), "right")


if __name__ == "__main__":
    unittest.main()
