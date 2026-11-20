import json
import unittest
import urllib.parse
from unittest.mock import patch

from hoverling.core import Target, explicit_target
from hoverling.translate import DEFAULTS, Settings, Translator, TranslationError

YOUDAO = {**DEFAULTS, "network_enabled": True, "network_provider": "youdao",
          "youdao_app_key": "test-key", "youdao_app_secret": "test-secret"}


class ExplicitSelectionTests(unittest.TestCase):
    def test_selection_is_not_expanded_to_a_phrase_or_context(self):
        target = explicit_target("piece")
        self.assertEqual((target.query, target.context), ("piece", "piece"))
        self.assertTrue(target.explicit)
        self.assertFalse(target.phrase)

    def test_entire_selected_sentence_stays_intact(self):
        text = "The task is a piece of cake.\nPlease keep this entire sentence."
        target = explicit_target(text)
        self.assertEqual(target.query, text)
        self.assertEqual(target.context, text)
        self.assertIn("小菜一碟", target.explanation)
        self.assertEqual(target.explanation.count("小菜一碟"), 1)

    def test_empty_and_oversize_selection_are_rejected_without_truncation(self):
        for text in ("", " \n\t ", "x" * 5001):
            with self.assertRaises(ValueError):
                explicit_target(text)
        self.assertEqual(len(explicit_target("x" * 5000).query), 5000)

    def test_phrase_does_not_cross_punctuation(self):
        self.assertFalse(explicit_target("Give. Up is another word.").phrase)

    def test_selected_youdao_text_is_not_cut_to_480_bytes(self):
        text = "This is the selected sentence. " * 35
        with patch("hoverling.translate.request_json", return_value={"errorCode": "0", "translation": ["完整译文"]}) as request:
            Translator().translate(explicit_target(text), YOUDAO)
            self.assertEqual(request.call_args.args[1]["q"], text.strip())
            self.assertGreater(len(request.call_args.args[1]["q"].encode()), 480)

    def test_context_action_cannot_send_unselected_surroundings(self):
        target = Target("selected words", "selected words", "NEVER_SEND_SCREEN_CONTEXT", explicit=True)
        with patch("hoverling.translate.request_json", return_value={"errorCode": "0", "translation": ["所选译文"]}) as request:
            Translator().translate(target, YOUDAO, sentence=True)
            self.assertEqual(request.call_args.args[1]["q"], "selected words")
            self.assertNotIn("NEVER_SEND_SCREEN_CONTEXT", repr(request.call_args))

    def test_google_uses_exact_selection_even_if_context_action_is_requested(self):
        target = Target("only this", "only this", "NEVER_SEND_SCREEN_CONTEXT", explicit=True)
        with patch("hoverling.translate.request_json", return_value=[[["只翻译这些", "only this"]]]) as request:
            Translator().translate(target, {**DEFAULTS, "network_enabled": True}, sentence=True)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(request.call_args.args[0]).query)
            self.assertEqual(query["q"], ["only this"])

    def test_ai_payload_contains_only_the_user_selected_range(self):
        target = Target("run", "run", "NEVER_SEND_SCREEN_CONTEXT", explicit=True)
        settings = {**DEFAULTS, "ai_enabled": True, "api_key": "test-key"}
        with patch("hoverling.translate.request_json", return_value={"choices": [{"message": {"content": "所选词义"}}]}) as request:
            Translator().translate(target, settings, sentence=True)
            payload = request.call_args.args[1]
            self.assertEqual(json.loads(payload["messages"][1]["content"]), {"selected_text": "run"})
            self.assertNotIn("NEVER_SEND_SCREEN_CONTEXT", json.dumps(payload))

    def test_hover_ai_cache_is_not_used_for_selection_explanations(self):
        settings = {**DEFAULTS, "ai_enabled": True, "api_key": "test-key"}
        translator = Translator()
        with patch("hoverling.translate.request_json", return_value={"choices": [{"message": {"content": "解释"}}]}) as request:
            translator.translate(Target("run", "run", "run"), settings)
            translator.translate(Target("run", "run", "run", explicit=True), settings)
            self.assertEqual(request.call_count, 2)

    def test_mymemory_rejects_oversize_selection_instead_of_silently_cutting_it(self):
        with patch("hoverling.translate.request_json", side_effect=AssertionError("network")):
            with self.assertRaisesRegex(TranslationError, "不会自动截断"):
                Translator().translate(explicit_target("hello " * 100), {**DEFAULTS, "network_enabled": True, "network_provider": "mymemory"})

    def test_selected_word_has_offline_definition_without_network(self):
        with patch("hoverling.translate.request_json", side_effect=AssertionError("network")):
            text, source = Translator().translate(explicit_target("bank"), DEFAULTS)
            self.assertIn("银行", text)
            self.assertIn("离线", source)

    def test_default_mode_is_selection(self):
        self.assertEqual(DEFAULTS["trigger"], "selection")


if __name__ == "__main__":
    unittest.main()
