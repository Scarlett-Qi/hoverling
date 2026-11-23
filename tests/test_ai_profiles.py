import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hoverling.core import explicit_target
from hoverling.profiles import AIProfiles
from hoverling.translate import Settings, Translator


class AIProfileTests(unittest.TestCase):
    def test_legacy_config_switch_restart_and_routing(self):
        first = {"api_base": "https://first.example/v1", "model": "first", "api_key": "first-key"}
        second = {"api_base": "https://second.example/v1", "model": "second", "api_key": "second-key"}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({**first, "ai_enabled": True}), encoding="utf-8")
            settings = Settings(path)
            draft = AIProfiles(settings.values)
            self.assertEqual(draft.current, {**first, "name": "默认配置"})
            draft.add()
            self.assertEqual(draft.current["api_key"], "")
            draft.current.update(second, name="第二套")
            settings.save(draft.settings())
            settings.save({"trigger": "alt"})
            settings = Settings(path)
            draft = AIProfiles(settings.values)
            self.assertEqual((draft.index, draft.labels()), (1, ["默认配置", "第二套"]))
            target = explicit_target("example")
            translator = Translator()
            response = {"choices": [{"message": {"content": "示例"}}]}
            with patch("hoverling.translate.request_json", return_value=response) as request:
                for index, expected in [(1, second), (0, first)]:
                    draft.index = index
                    settings.save(draft.settings())
                    translator.translate(target, settings.values)
                    endpoint, payload, key = request.call_args.args
                    self.assertEqual((endpoint, payload["model"], key),
                                     (expected["api_base"] + "/chat/completions", expected["model"], expected["api_key"]))
                self.assertEqual(request.call_count, 2)
            self.assertEqual(Settings(path).values["active_ai_profile"], 0)
            self.assertNotIn("api_key", json.loads(path.read_text(encoding="utf-8")))

    def test_cancel_and_remove_do_not_change_saved_profiles(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings(Path(folder) / "settings.json")
            settings.save({"api_key": "original"})
            draft = AIProfiles(settings.values)
            draft.current["api_key"] = "edited"
            draft.add()
            draft.remove()
            self.assertEqual(settings.values["ai_profiles"][0]["api_key"], "original")
            draft.remove()
            self.assertEqual(len(draft.items), 1)
