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
                       "youdao_app_secret": "example-youdao-secret"}
            settings.save(secrets)
            settings.save({"network_provider": "deepl"})
            reloaded = WindowsSettings(path)
            contents = path.read_text(encoding="utf-8")
            for key, value in secrets.items():
                self.assertNotIn(value, contents)
                self.assertEqual(reloaded.values[key], value)
