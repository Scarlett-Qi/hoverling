import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from hoverling.core import Target
from hoverling.translate import DEFAULTS, Settings, Translator, TranslationError


class MultilingualTests(unittest.TestCase):
    def target(self, text):
        return Target(text, text, "NEVER_SEND_SURROUNDINGS", explicit=True)

    def test_automatic_providers_keep_non_english_selection_and_chinese_target(self):
        settings = {**DEFAULTS, "network_enabled": True,
                    "youdao_app_key": "test-key", "youdao_app_secret": "test-secret",
                    "google_cloud_key": "test-key", "deepl_api_key": "test-key"}
        responses = {
            "youdao": {"errorCode": "0", "translation": ["模拟译文"]},
            "google_cloud": {"data": {"translations": [{"translatedText": "模拟译文"}]}},
            "deepl": {"translations": [{"text": "模拟译文"}]},
        }
        for text in ("いらっしゃいませ", "안녕하세요", "Bonjour !", "Привет!", "日本語 and English"):
            for provider, response in responses.items():
                with self.subTest(text=text, provider=provider), patch(
                        "hoverling.translate.request_json", return_value=response) as request:
                    result, _ = Translator().translate(self.target(text), {**settings, "network_provider": provider}, sentence=True)
                    self.assertEqual(result, "模拟译文")
                    self.assertNotIn("NEVER_SEND_SURROUNDINGS", repr(request.call_args))
                    if provider == "google_cloud":
                        payload = request.call_args.args[1]
                        self.assertEqual(payload["q"], text)
                        self.assertNotIn("source", payload)
                        self.assertEqual(payload["target"], "zh-CN")
                    elif provider == "youdao":
                        payload = request.call_args.args[1]
                        self.assertEqual(payload["q"], text)
                        self.assertEqual(payload["from"], "auto")
                        self.assertEqual(payload["to"], "zh-CHS")
                        self.assertEqual(payload["strict"], "true")
                    else:
                        payload = request.call_args.args[1]
                        self.assertEqual(payload["text"], [text])
                        self.assertNotIn("source_lang", payload)
                        self.assertEqual(payload["target_lang"], "ZH-HANS")

    def test_ai_handles_original_language_without_extra_context(self):
        settings = {**DEFAULTS, "ai_enabled": True, "api_key": "test-key"}
        with patch("hoverling.translate.request_json", return_value={"choices": [{"message": {"content": "模拟解释"}}]}) as request:
            Translator().translate(self.target("いらっしゃいませ"), settings)
            messages = request.call_args.args[1]["messages"]
            self.assertEqual(json.loads(messages[1]["content"]), {"selected_text": "いらっしゃいませ"})
            self.assertIn("自动识别原文语言", messages[0]["content"])
            self.assertIn("简体中文", messages[0]["content"])
            self.assertNotIn("英汉", messages[0]["content"])
            self.assertNotIn("NEVER_SEND_SURROUNDINGS", repr(messages))

    def test_mymemory_manual_language_is_used_and_cache_is_separate(self):
        translator = Translator()
        settings = {**DEFAULTS, "network_enabled": True, "network_provider": "mymemory"}
        with patch("hoverling.translate.request_json", return_value={"responseData": {"translatedText": "模拟译文"}}) as request:
            for code, name in (("en", "英语"), ("ja", "日语"), ("ko", "韩语")):
                selected = {**settings, "mymemory_source": code}
                _, source = translator.translate(self.target("test"), selected)
                translator.translate(self.target("test"), selected)
                payload = urllib.parse.parse_qs(urllib.parse.urlparse(request.call_args.args[0]).query)
                self.assertEqual(payload["langpair"], [code + "|zh-CN"])
                self.assertIn(name + " → 简体中文", source)
            self.assertEqual(request.call_count, 3)

    def test_mymemory_does_not_send_an_invalid_auto_language(self):
        with patch("hoverling.translate.request_json", side_effect=AssertionError("network")):
            with self.assertRaisesRegex(TranslationError, "需要指定源语言"):
                Translator().translate(self.target("いらっしゃいませ"), {
                    **DEFAULTS, "network_enabled": True, "network_provider": "mymemory", "mymemory_source": "auto"})

    def test_source_setting_persists_and_old_configs_keep_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{"network_provider":"youdao"}')
            settings = Settings(path)
            self.assertEqual(settings.values["mymemory_source"], "en")
            settings.save({"mymemory_source": "ja"})
            self.assertEqual(Settings(path).values["mymemory_source"], "ja")
            for invalid in ("auto", None, [], {}):
                path.write_text(json.dumps({"mymemory_source": invalid}))
                self.assertEqual(Settings(path).values["mymemory_source"], "en")


if __name__ == "__main__":
    unittest.main()
