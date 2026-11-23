import json
import unittest
from unittest.mock import patch

from hoverling.core import explicit_target
from hoverling.translate import DEFAULTS, Translator, TranslationError


class GoogleCloudTests(unittest.TestCase):
    def setUp(self):
        self.target = explicit_target("fish & chips")
        self.config = dict(DEFAULTS, network_provider="google_cloud", network_enabled=True,
                           google_cloud_key="test-project-key")

    @patch("urllib.request.build_opener")
    def test_official_endpoint_and_cached_result(self, opener):
        response = opener.return_value.open.return_value.__enter__.return_value
        response.read.return_value = b'{"data":{"translations":[{"translatedText":"A &amp; B"}]}}'
        translator = Translator()
        self.assertEqual(translator.translate(self.target, self.config)[0], "A & B")
        translator.translate(self.target, self.config)
        opener.return_value.open.assert_called_once()
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://translation.googleapis.com/language/translate/v2")
        self.assertEqual(request.get_header("X-goog-api-key"), "test-project-key")
        self.assertEqual(json.loads(request.data), {"q":"fish & chips", "format":"text", "target":"zh-CN", "model":"nmt"})

    @patch("hoverling.translate.request_json")
    def test_missing_key_and_malformed_result(self, request):
        with self.assertRaises(TranslationError):
            Translator().translate(self.target, dict(self.config, google_cloud_key=""))
        request.assert_not_called()
        request.return_value = {"data":{"translations":[]}}
        with self.assertRaises(TranslationError):
            Translator().translate(self.target, self.config)
