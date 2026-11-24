import io
import json
import urllib.error
import unittest
from unittest.mock import patch

from hoverling.core import Target
from hoverling.translate import DEFAULTS, TranslationError, Translator


class DoubaoTranslationTests(unittest.TestCase):
    def setUp(self):
        self.target = Target("Good morning!", "Good morning!", "surrounding sentence", explicit=True)
        self.config = dict(DEFAULTS, network_enabled=True, network_provider="doubao",
                           doubao_api_key="test-ark", api_key="separate-ai-key")

    @patch("urllib.request.build_opener")
    def test_request_uses_ark_key_selection_and_responses_api(self, opener):
        response = {"status": "completed", "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": "早上"}, {"type": "output_text", "text": "好！"}]}]}
        opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
        translator = Translator()
        for _ in range(2):
            text, source = translator.translate(self.target, self.config, sentence=True)
            self.assertEqual(text, "早上好！")
            self.assertIn("豆包翻译", source)
        opener.return_value.open.assert_called_once()
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://ark.cn-beijing.volces.com/api/v3/responses")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-ark")
        self.assertEqual(json.loads(request.data), {"model": "doubao-seed-translation-250915",
                         "input": [{"role": "user", "content": [{"type": "input_text", "text": self.target.query,
                                    "translation_options": {"target_language": "zh"}}]}]})
        with self.assertRaisesRegex(TranslationError, "火山方舟 API Key"):
            translator.translate(self.target, dict(self.config, doubao_api_key=""))
        opener.return_value.open.assert_called_once()

    @patch("urllib.request.build_opener")
    def test_bad_request_shows_provider_detail_and_handles_non_json(self, opener):
        for body, expected in [
            (b'{"error":{"code":"InvalidParameter","message":"store is not supported by translation model"}}',
             "store is not supported"),
            (b"Bad Request", "HTTP 400"),
            (b'{"error":{"message":"Invalid token: test-ark"}}', "已隐藏"),
        ]:
            with self.subTest(body=body):
                opener.return_value.open.side_effect = urllib.error.HTTPError(
                    "https://ark.cn-beijing.volces.com/api/v3/responses", 400, "Bad Request", {}, io.BytesIO(body))
                with self.assertRaisesRegex(TranslationError, expected) as raised:
                    Translator().translate(self.target, self.config)
                self.assertNotIn("test-ark", str(raised.exception))

    @patch("hoverling.translate.request_json")
    def test_failed_and_empty_responses_are_not_displayed_or_cached(self, request):
        translator = Translator()
        for status, output in [("incomplete", []), ("completed", []), ("completed", 4)]:
            request.return_value = {"status": status, "output": output}
            with self.assertRaises(TranslationError):
                translator.translate(self.target, self.config)
        self.assertEqual(request.call_count, 3)
