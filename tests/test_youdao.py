import io
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from hoverling.core import Target
from hoverling.translate import DEFAULTS, Settings, Translator, TranslationError, request_json, youdao_params, parse_youdao

YOUDAO = {**DEFAULTS, "network_enabled": True, "network_provider": "youdao",
          "youdao_app_key": "app123", "youdao_app_secret": "secret123"}


class YoudaoTests(unittest.TestCase):
    def test_v3_short_query_signature_fixture(self):
        payload = youdao_params("hello", "app123", "secret123", salt="salt123", curtime="1700000000")
        self.assertEqual(payload["sign"], "d687f47f347ae6529cff3272c89c214643b1570d1d87fdad2a6870315b6e39a2")
        self.assertEqual(payload["signType"], "v3")
        self.assertNotIn("secret123", urllib.parse.urlencode(payload))

    def test_v3_long_query_signature_fixture(self):
        payload = youdao_params("abcdefghijklmnopqrstu", "app123", "secret123", salt="salt123", curtime="1700000000")
        self.assertEqual(payload["sign"], "e1532a0f13a92c3eda195c321c054c0f49e8cbffa2c0768d55ab632e047f5209")
        self.assertEqual(payload["q"], "abcdefghijklmnopqrstu")

    def test_requests_use_fresh_salts(self):
        first = youdao_params("hello", "app123", "secret123")
        second = youdao_params("hello", "app123", "secret123")
        self.assertNotEqual(first["salt"], second["salt"])
        self.assertTrue(first["curtime"].isdigit())

    def test_form_encoding_keeps_unicode_and_symbols(self):
        payload = youdao_params("hello 世界 & ?", "app123", "secret123")
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(b'{"errorCode":"0","translation":["hello"]}')
            request_json("https://openapi.youdao.com/api", payload, form=True)
            request = opener.return_value.open.call_args.args[0]
            body = urllib.parse.parse_qs(request.data.decode())
            self.assertEqual(body["q"], ["hello 世界 & ?"])
            self.assertEqual(request.get_method(), "POST")
            self.assertTrue(request.get_header("Content-type").startswith("application/x-www-form-urlencoded"))
            self.assertNotIn(b"secret123", request.data)
            self.assertNotIn("secret123", request.full_url)

    def test_translation_and_sentence_request(self):
        target = Target("cake", "a piece of cake", "Learning English is a piece of cake.")
        with patch("hoverling.translate.request_json", return_value={"errorCode": "0", "translation": ["学英语很容易。"]}) as request:
            text, source = Translator().translate(target, YOUDAO, sentence=True)
            self.assertEqual(text, "学英语很容易。")
            self.assertEqual(source, "有道智云 · 官方文本翻译")
            self.assertEqual(request.call_args.args[0], "https://openapi.youdao.com/api")
            self.assertEqual(request.call_args.args[1]["q"], target.context)
            self.assertTrue(request.call_args.kwargs["form"])

    def test_missing_keys_are_reported_before_network(self):
        with patch("hoverling.translate.request_json", side_effect=AssertionError("network")):
            with self.assertRaisesRegex(TranslationError, "App Key"):
                Translator().translate(Target("bank", "bank", "bank"), {**YOUDAO, "youdao_app_secret": ""})

    def test_signing_and_account_errors_are_specific(self):
        for code, message in (("202", "签名"), ("110", "文本翻译服务"), ("206", "系统时间"), ("401", "欠费")):
            with self.subTest(code=code), self.assertRaisesRegex(TranslationError, message):
                parse_youdao({"errorCode": code})

    def test_malformed_response_does_not_look_successful(self):
        for result in ({}, {"errorCode": "0"}, {"errorCode": "0", "translation": []},
                       {"errorCode": "0", "translation": [None]}, {"errorCode": "0", "translation": [""]}):
            with self.subTest(result=result), self.assertRaises(TranslationError):
                parse_youdao(result)

    def test_api_failure_keeps_word_definition_with_visible_error(self):
        with patch("hoverling.translate.request_json", return_value={"errorCode": "401"}):
            text, source = Translator().translate(Target("bank", "bank", "bank"), YOUDAO)
            self.assertIn("银行", text)
            self.assertIn("已使用离线释义", source)
            self.assertIn("401", source)

    def test_sentence_error_is_not_disguised_as_word_translation(self):
        with patch("hoverling.translate.request_json", return_value={"errorCode": "202"}):
            with self.assertRaisesRegex(TranslationError, "202"):
                Translator().translate(Target("bank", "bank", "I went to the bank."), YOUDAO, sentence=True)

    def test_credential_change_does_not_reuse_account_cache(self):
        translator = Translator()
        target = Target("hello", "hello", "hello")
        with patch("hoverling.translate.request_json", return_value={"errorCode": "0", "translation": ["你好"]}) as request:
            translator.translate(target, YOUDAO)
            translator.translate(target, YOUDAO)
            self.assertEqual(request.call_count, 1)
            translator.translate(target, {**YOUDAO, "youdao_app_secret": "new-secret"})
            self.assertEqual(request.call_count, 2)
        self.assertNotIn("secret123", repr(translator.cache.keys()))
        self.assertNotIn("new-secret", repr(translator.cache.keys()))

    def test_offline_mode_sends_nothing_to_youdao(self):
        with patch("hoverling.translate.request_json", side_effect=AssertionError("network")):
            text, source = Translator().translate(Target("bank", "bank", "bank"), {**YOUDAO, "network_enabled": False})
            self.assertIn("银行", text)
            self.assertIn("离线", source)

    def test_credentials_and_provider_reload_from_private_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            settings = Settings(path)
            settings.save({"network_provider": "youdao", "youdao_app_key": "app123", "youdao_app_secret": "secret123"})
            loaded = Settings(path)
            self.assertEqual(loaded.values["network_provider"], "youdao")
            self.assertEqual(loaded.values["youdao_app_secret"], "secret123")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
