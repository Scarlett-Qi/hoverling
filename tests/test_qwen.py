import unittest
from unittest.mock import patch
from hoverling.core import explicit_target
from hoverling.translate import DEFAULTS,Translator


class QwenCompatibilityTests(unittest.TestCase):
    def request(self,base,model):
        settings={**DEFAULTS,'ai_enabled':True,'api_base':base,'model':model,'api_key':'placeholder-key'}
        with patch('hoverling.translate.request_json',return_value={'choices':[{'message':{'content':'译文与解释'}}]}) as request:
            text,source=Translator().translate(explicit_target("I'm down for the trip."),settings)
            self.assertEqual(text,'译文与解释')
            return request.call_args

    def test_qwen_plus_uses_non_thinking_with_longer_ai_timeout(self):
        call=self.request('https://dashscope.aliyuncs.com/compatible-mode/v1','qwen3.7-plus')
        self.assertIs(call.args[1]['enable_thinking'],False)
        self.assertEqual(call.kwargs['timeout'],45)
        self.assertFalse(call.args[1]['stream'])

    def test_workspace_host_supports_qwen_max(self):
        call=self.request('https://llm-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1','qwen4-max')
        self.assertIs(call.args[1]['enable_thinking'],False)

    def test_unknown_thinking_only_model_is_not_forced_to_disable_thinking(self):
        call=self.request('https://dashscope.aliyuncs.com/compatible-mode/v1','qwen3.7-max-preview')
        self.assertNotIn('enable_thinking',call.args[1])

    def test_third_party_and_lookalike_hosts_do_not_receive_qwen_specific_flags(self):
        for base in ('https://example.com/v1','https://dashscope.aliyuncs.com.example.org/v1'):
            with self.subTest(base=base):
                call=self.request(base,'qwen3.7-plus')
                self.assertNotIn('enable_thinking',call.args[1])


if __name__=='__main__':unittest.main()
