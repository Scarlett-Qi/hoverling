import unittest
import urllib.error
from unittest.mock import patch

from hoverling.updates import LATEST_URL, RELEASES, check_update, release_result


class UpdateTests(unittest.TestCase):
    def test_numeric_order_and_dev_builds(self):
        for installed, tag, newer in [("0.9.9", "v0.10.0", True), ("0.10.0", "v0.9.9", False),
                                      ("0.10.0", "v0.10.0", False), ("0.8.1-dev.1", "v0.8.1", True)]:
            with self.subTest(installed=installed, tag=tag):
                message, link = release_result(f"{RELEASES}/tag/{tag}", installed)
                if newer:
                    self.assertEqual(link, f"https://github.com/Scarlett-Qi/hoverling/releases/tag/{tag}")
                    self.assertIn(tag, message)
                else:
                    self.assertIsNone(link)

    def test_invalid_releases_are_rejected(self):
        for url in [LATEST_URL, f"{RELEASES}/tag/v1.0.0/extra", f"{RELEASES}/tag/v1.0.0-beta",
                    "https://example.org/releases/tag/v1.0.0"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                release_result(url, "0.8.0")

    @patch("urllib.request.urlopen")
    def test_public_head_and_no_credentials(self, open_url):
        open_url.return_value.__enter__.return_value.geturl.return_value = RELEASES + "/tag/v20.0.0"
        self.assertIsNotNone(check_update()[1])
        req = open_url.call_args.args[0]
        self.assertEqual(req.full_url, LATEST_URL)
        self.assertEqual(req.get_method(), "HEAD")
        self.assertIsNone(req.get_header("Authorization"))
        self.assertGreater(open_url.call_args.kwargs["timeout"], 0)

    @patch("urllib.request.urlopen")
    def test_errors_allow_retry(self, open_url):
        for error, reason in [(urllib.error.HTTPError(LATEST_URL, 403, "rate limit",
                                                       {"X-RateLimit-Remaining": "0"}, None), "请求受限"),
                              (TimeoutError(), "失败")]:
            open_url.side_effect = error
            message, link = check_update()
            self.assertIn(reason, message)
            self.assertIsNone(link)
        open_url.side_effect = None
        open_url.return_value.__enter__.return_value.geturl.return_value = LATEST_URL
        self.assertIn("失败", check_update()[0])
