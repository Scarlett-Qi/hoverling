import sys
from pathlib import Path
import tempfile
import unittest


@unittest.skipUnless(sys.platform == "win32", "DPAPI is provided by Windows")
class WindowsSettingsTests(unittest.TestCase):
    def test_secrets_survive_an_unrelated_edit_without_plaintext_on_disk(self):
        from hoverling.windows.secrets import WindowsSettings

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            settings = WindowsSettings(path)
            secrets = {"api_key": "example-ai-token", "deepl_api_key": "example-deepl-token",
                       "google_cloud_key": "example-cloud-key", "youdao_app_secret": "example-youdao-secret"}
            settings.save(secrets)
            settings.save({"network_provider": "deepl"})
            reloaded = WindowsSettings(path)
            contents = path.read_text(encoding="utf-8")
            for key, value in secrets.items():
                self.assertNotIn(value, contents)
                self.assertEqual(reloaded.values[key], value)

    def test_migrates_old_dpapi_key_and_protects_inactive_profiles(self):
        import json
        from hoverling.profiles import AIProfiles
        from hoverling.windows.secrets import WindowsSettings, encode_key

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            path.write_text(json.dumps({"api_key": encode_key("first-private")}), encoding="utf-8")
            settings = WindowsSettings(path)
            draft = AIProfiles(settings.values)
            self.assertEqual(draft.current["api_key"], "first-private")
            draft.add()
            draft.current["api_key"] = "second-private"
            settings.save(draft.settings())
            settings.save({"trigger": "alt"})
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("api_key", data)
            for profile in data["ai_profiles"]:
                self.assertTrue(profile["api_key"].startswith("dpapi:"))
            loaded = WindowsSettings(path).values
            self.assertEqual(loaded["api_key"], "second-private")
            self.assertEqual([p["api_key"] for p in loaded["ai_profiles"]], ["first-private", "second-private"])
