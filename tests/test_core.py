import os
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hoverling.core import Target, Word, clip_utf8, local_target, parse_tsv, target_at
from hoverling.translate import DEFAULTS, NoRedirect, Settings, TranslationError, Translator, api_url, request_json

GOOGLE = {**DEFAULTS, "network_enabled": True, "network_provider": "google_cloud", "google_cloud_key": "test-key"}


class RecognitionTests(unittest.TestCase):
    def test_idiom_contains_hovered_word(self):
        text = "This is a piece of cake."
        start = text.index("piece")
        target = local_target(text, start, start + 5)
        self.assertEqual(target.query, "a piece of cake")
        self.assertIn("小菜一碟", target.explanation)

    def test_unrelated_idiom_is_not_attached(self):
        text = "English is a piece of cake."
        self.assertFalse(local_target(text, 0, 7).phrase)

    def test_not_across_sentence_boundary(self):
        text = "Give. Up here is the sign."
        self.assertFalse(local_target(text, 0, 4).phrase)

    def test_apostrophe_normalization(self):
        self.assertTrue(local_target("I’m down for that.", 4, 8).phrase)

    def test_native_tsv_without_header(self):
        row = "5\t1\t1\t1\t1\t1\t20\t30\t80\t25\t96\tEnglish\n"
        self.assertEqual(parse_tsv(row)[0].text, "English")
        header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        self.assertEqual(parse_tsv(header + row), parse_tsv(row))

    def test_hover_must_be_over_text(self):
        words = [Word("English", 10, 20, 80, 25, 96, (1, 1, 1, 1))]
        self.assertIsNone(target_at(words, 1000, 1000))
        self.assertEqual(target_at(words, 40, 30).word, "English")

    def test_single_letter_english_words(self):
        for word in ("a", "I"):
            self.assertEqual(target_at([Word(word, 10, 20, 10, 25, 96, (1, 1, 1, 1))], 15, 30).word, word)

    def test_wrapped_phrase(self):
        words = [Word("a", 10, 10, 15, 20, 96, (1, 1, 1, 1)),
                 Word("piece", 35, 10, 65, 20, 96, (1, 1, 1, 1)),
                 Word("of", 10, 40, 25, 20, 96, (1, 1, 1, 2)),
                 Word("cake.", 45, 40, 60, 20, 96, (1, 1, 1, 2))]
        self.assertTrue(target_at(words, 65, 50).phrase)

    def test_utf8_byte_limit(self):
        value = clip_utf8("中" * 300)
        self.assertLessEqual(len(value.encode()), 480)
        self.assertNotIn("�", value)


class TranslationTests(unittest.TestCase):
    def test_local_phrase_never_uses_network(self):
        target = Target("piece", "a piece of cake", "It is a piece of cake.", "小菜一碟", True)
        with patch("hoverling.translate.request_json", side_effect=AssertionError("network")):
            self.assertEqual(Translator().translate(target, {**DEFAULTS, "network_enabled": False})[0], "小菜一碟")

    def test_offline_unknown_never_uses_network(self):
        with patch("hoverling.translate.request_json", side_effect=AssertionError("network")):
            text, source = Translator().translate(Target("qzzxxzz", "qzzxxzz", "qzzxxzz"), {**DEFAULTS, "network_enabled": False})
            self.assertEqual(source, "离线模式")
            self.assertIn("未收录", text)

    def test_online_quota_failure_is_explicit(self):
        with patch("hoverling.translate.request_json", return_value={"responseStatus": 403}):
            with self.assertRaises(TranslationError):
                Translator().translate(Target("test", "test", "test sentence"), {**DEFAULTS, "network_enabled": True, "network_provider": "mymemory"}, sentence=True)

    def test_google_translates_whole_sentence_context(self):
        response = {"data": {"translations": [{"translatedText": "第一句。第二句。"}]}}
        target = Target("First", "First", "First. Second.")
        with patch("hoverling.translate.request_json", return_value=response) as request:
            text, source = Translator().translate(target, GOOGLE, sentence=True)
            self.assertEqual(text, "第一句。第二句。")
            self.assertIn("Google Cloud", source)
            self.assertEqual(request.call_args.args[1]["q"], target.context)

    def test_google_translates_even_when_word_is_in_local_dictionary(self):
        response = {"data": {"translations": [{"translatedText": "银行"}]}}
        with patch("hoverling.translate.request_json", return_value=response) as request:
            text, source = Translator().translate(Target("bank", "bank", "river bank"), GOOGLE)
            self.assertEqual(text, "银行")
            self.assertEqual(request.call_count, 1)
            self.assertIn("Google Cloud", source)

    def test_old_web_setting_uses_official_api_and_existing_key(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({**GOOGLE, "network_provider": "google_web"}))
            settings = Settings(path)
            self.assertEqual(settings.values["network_provider"], "google_cloud")
            with patch("hoverling.translate.translate_google_cloud", return_value="银行") as cloud:
                Translator().translate(Target("bank", "bank", "bank"), settings.values)
                cloud.assert_called_once_with("bank", "test-key")

    def test_old_web_setting_without_key_prompts_before_request(self):
        settings = {**GOOGLE, "network_provider": "google_web", "google_cloud_key": ""}
        with patch("hoverling.translate.request_json") as request:
            with self.assertRaisesRegex(TranslationError, "Google Cloud Translation API Key"):
                Translator().translate(Target("bank", "bank", "bank"), settings)
            request.assert_not_called()

    def test_google_sentence_outage_does_not_invent_sentence_translation(self):
        with patch("hoverling.translate.request_json", side_effect=TranslationError("网络不通")):
            with self.assertRaises(TranslationError):
                Translator().translate(Target("bank", "bank", "I went to the bank."), GOOGLE, sentence=True)

    def test_provider_switch_does_not_reuse_wrong_cache(self):
        translator = Translator()
        target = Target("bank", "bank", "bank")
        with patch("hoverling.translate.request_json", return_value={"data": {"translations": [{"translatedText": "谷歌结果"}]}}):
            self.assertEqual(translator.translate(target, GOOGLE)[0], "谷歌结果")
        with patch("hoverling.translate.request_json", return_value={"responseData": {"translatedText": "另一服务结果"}}) as request:
            self.assertEqual(translator.translate(target, {**GOOGLE, "network_provider": "mymemory"})[0], "另一服务结果")
            self.assertEqual(request.call_count, 1)

    def test_json_arrays_are_rejected(self):
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(b'[[["hello"]]]')
            with self.assertRaises(TranslationError):
                request_json("https://example.com")

    def test_api_redirect_is_not_followed(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://example.com"))

    def test_ai_receives_context_and_caches_only_this_context(self):
        settings = {**DEFAULTS, "ai_enabled": True, "api_key": "test-key"}
        result = {"choices": [{"message": {"content": "这是针对上下文的解释。"}}]}
        with patch("hoverling.translate.request_json", return_value=result) as request:
            translator = Translator()
            first = Target("bank", "bank", "The bank approved my loan.")
            translator.translate(first, settings)
            translator.translate(first, settings)
            translator.translate(Target("bank", "bank", "On the river bank."), settings)
            self.assertEqual(request.call_count, 2)
            self.assertIn("river bank", request.call_args.args[1]["messages"][1]["content"])

    def test_reject_plaintext_remote_key_transport(self):
        with self.assertRaises(TranslationError):
            api_url("http://example.com/v1")
        self.assertEqual(api_url("http://localhost:11434/v1"), "http://localhost:11434/v1/chat/completions")
        self.assertEqual(api_url("https://example.com/v1/chat/completions"), "https://example.com/v1/chat/completions")

    def test_secret_file_permissions_and_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config" / "settings.json"
            settings = Settings(path)
            settings.save({"api_key": "a-test-key"})
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(Settings(path).values["api_key"], "a-test-key")

    def test_invalid_config_uses_safe_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{"delay":null,"ai_enabled":"yes","network_enabled":"yes"}')
            settings = Settings(path)
            self.assertFalse(settings.values["ai_enabled"])
            self.assertFalse(settings.values["network_enabled"])
            self.assertEqual(settings.values["delay"], DEFAULTS["delay"])


if __name__ == "__main__":
    unittest.main()
