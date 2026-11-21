import os
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
from hoverling.core import Target,explicit_target
from hoverling.translate import DEFAULTS,Settings,Translator,TranslationError,DeepLRequestLimiter,deepl_endpoint,translate_deepl,request_json

DEEPL={**DEFAULTS,'network_enabled':True,'network_provider':'deepl','deepl_api_key':'placeholder:fx'}


class DeepLTests(unittest.TestCase):
    def setUp(self):
        self.limiter_patch=patch('hoverling.translate.DEEPL_LIMITER',DeepLRequestLimiter())
        self.limiter_patch.start()
        self.addCleanup(self.limiter_patch.stop)

    def test_endpoint_selection_and_overrides(self):
        self.assertEqual(deepl_endpoint('placeholder:fx'),'https://api-free.deepl.com/v2/translate')
        self.assertEqual(deepl_endpoint('placeholder'),'https://api.deepl.com/v2/translate')
        self.assertEqual(deepl_endpoint('placeholder:fx','standard'),'https://api.deepl.com/v2/translate')
        self.assertEqual(deepl_endpoint('placeholder','free'),'https://api-free.deepl.com/v2/translate')
        with self.assertRaises(TranslationError):deepl_endpoint('')
        with self.assertRaises(TranslationError):deepl_endpoint('placeholder','arbitrary-host')

    def test_json_payload_uses_exact_selection_and_no_extra_context(self):
        target=Target('only selected','only selected','DO_NOT_SEND_SURROUNDINGS',explicit=True)
        with patch('hoverling.translate.request_json',return_value={'translations':[{'text':'只翻译所选'}]}) as request:
            text,source=Translator().translate(target,DEEPL,sentence=True)
            self.assertEqual(text,'只翻译所选')
            self.assertEqual(source,'DeepL · 官方文本翻译')
            self.assertEqual(request.call_args.args[1],{'text':['only selected'],'target_lang':'ZH-HANS'})
            self.assertEqual(request.call_args.kwargs['auth_scheme'],'DeepL-Auth-Key')
            self.assertNotIn('DO_NOT_SEND_SURROUNDINGS',repr(request.call_args))

    def test_full_selection_is_not_truncated(self):
        text='selected sentence '*80
        with patch('hoverling.translate.request_json',return_value={'translations':[{'text':'完整译文'}]}) as request:
            Translator().translate(explicit_target(text),DEEPL)
            self.assertEqual(request.call_args.args[1]['text'],[text.strip()])

    def test_authentication_is_in_header_only(self):
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=io.BytesIO(b'{"translations":[{"text":"hello"}]}')
            translate_deepl('hello','placeholder:fx')
            request=opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header('Authorization'),'DeepL-Auth-Key placeholder:fx')
            self.assertNotIn('placeholder',request.full_url)
            self.assertNotIn(b'placeholder',request.data)
            self.assertEqual(json.loads(request.data)['text'],['hello'])

    def test_quota_and_authentication_http_errors_are_specific(self):
        for code,expected in ((456,'额度'),(403,'接口类型'),(429,'频繁')):
            with self.subTest(code=code),patch('urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect=urllib.error.HTTPError('https://api-free.deepl.com/v2/translate',code,'error',{},None)
                with self.assertRaisesRegex(TranslationError,expected):translate_deepl('hello','placeholder:fx')

    def test_malformed_response_is_not_success(self):
        for result in ({},{'translations':[]},{'translations':[{}]},{'translations':[{'text':None}]},{'translations':[{'text':''}]}):
            with self.subTest(result=result),patch('hoverling.translate.request_json',return_value=result):
                with self.assertRaises(TranslationError):translate_deepl('hello','placeholder:fx')

    def test_missing_key_does_not_send_request(self):
        with patch('hoverling.translate.request_json',side_effect=AssertionError('network')):
            with self.assertRaisesRegex(TranslationError,'DeepL API Key'):
                Translator().translate(explicit_target('bank'),{**DEEPL,'deepl_api_key':''})

    def test_cache_is_isolated_by_key_and_endpoint(self):
        translator=Translator();target=explicit_target('hello')
        with patch('hoverling.translate.request_json',return_value={'translations':[{'text':'你好'}]}) as request:
            translator.translate(target,DEEPL);translator.translate(target,DEEPL)
            self.assertEqual(request.call_count,1)
            translator.translate(target,{**DEEPL,'deepl_api_key':'different-key'})
            translator.translate(target,{**DEEPL,'deepl_server':'standard'})
            self.assertEqual(request.call_count,3)
        self.assertNotIn('placeholder',repr(translator.cache.keys()))
        self.assertNotIn('different-key',repr(translator.cache.keys()))

    def test_key_and_endpoint_survive_private_config_save(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json';settings=Settings(path)
            settings.save({'network_provider':'deepl','deepl_api_key':'placeholder:fx','deepl_server':'free'})
            loaded=Settings(path)
            self.assertEqual(loaded.values['deepl_api_key'],'placeholder:fx')
            self.assertEqual(loaded.values['network_provider'],'deepl')
            self.assertEqual(loaded.values['deepl_server'],'free')
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode&0o777,0o600)


if __name__=='__main__':unittest.main()
