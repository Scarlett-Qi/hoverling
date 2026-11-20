import threading
import unittest
import urllib.error
from email.utils import formatdate
from unittest.mock import Mock,patch
from hoverling.translate import (DeepLRequestLimiter,DeepLRateLimitError,TranslationError,
                                request_json,retry_after_seconds,translate_deepl)


class DeepLRateLimitTests(unittest.TestCase):
    def test_rate_limit_enters_cooldown_without_repeating_the_http_call(self):
        now=[100.0];limiter=DeepLRequestLimiter(lambda:now[0])
        request=Mock(side_effect=DeepLRateLimitError('limited'))
        with self.assertRaises(DeepLRateLimitError) as caught:limiter.run('endpoint','secret-key',request)
        self.assertEqual(caught.exception.retry_after,30)
        now[0]+=10
        with self.assertRaisesRegex(DeepLRateLimitError,'20 秒'):limiter.run('endpoint','secret-key',request)
        self.assertEqual(request.call_count,1)
        self.assertNotIn('secret-key',repr(limiter.states))

    def test_backoff_grows_and_success_resets_it(self):
        now=[0.0];limiter=DeepLRequestLimiter(lambda:now[0])
        limited=Mock(side_effect=DeepLRateLimitError('limited'))
        for delay in (30,60,120,240,300):
            with self.assertRaises(DeepLRateLimitError) as caught:limiter.run('endpoint','key',limited)
            self.assertEqual(caught.exception.retry_after,delay)
            now[0]+=delay
        self.assertEqual(limiter.run('endpoint','key',lambda:'success'),'success')
        with self.assertRaises(DeepLRateLimitError) as caught:limiter.run('endpoint','key',limited)
        self.assertEqual(caught.exception.retry_after,30)

    def test_server_retry_after_is_respected(self):
        now=[0.0];limiter=DeepLRequestLimiter(lambda:now[0])
        request=Mock(side_effect=DeepLRateLimitError('limited',retry_after=120))
        with self.assertRaises(DeepLRateLimitError) as caught:limiter.run('endpoint','key',request)
        self.assertEqual(caught.exception.retry_after,120)
        now[0]=119
        with self.assertRaises(DeepLRateLimitError):limiter.run('endpoint','key',request)
        self.assertEqual(request.call_count,1)

    def test_same_key_has_only_one_in_flight_request(self):
        limiter=DeepLRequestLimiter();started=threading.Event();release=threading.Event();errors=[]
        def action():
            started.set()
            if not release.wait(2):raise AssertionError('test timed out')
            return 'ok'
        def first():
            try:limiter.run('endpoint','key',action)
            except Exception as exc:errors.append(exc)
        thread=threading.Thread(target=first);thread.start()
        try:
            self.assertTrue(started.wait(1))
            duplicate=Mock()
            with self.assertRaisesRegex(TranslationError,'还在处理中'):limiter.run('endpoint','key',duplicate)
            duplicate.assert_not_called()
        finally:release.set();thread.join(2)
        self.assertFalse(errors)
        self.assertEqual(limiter.run('endpoint','key',lambda:'next'),'next')

    def test_numeric_and_date_retry_after_headers(self):
        self.assertEqual(retry_after_seconds('3.2'),4)
        self.assertIsNone(retry_after_seconds('not-a-header'))
        self.assertIsNone(retry_after_seconds('NaN'))
        with patch('hoverling.translate.time.time',return_value=1700000000):
            self.assertEqual(retry_after_seconds(formatdate(1700000120,usegmt=True)),120)

    def test_http_429_preserves_retry_after_and_quota_is_not_retried(self):
        url='https://api-free.deepl.com/v2/translate'
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=urllib.error.HTTPError(url,429,'limited',{'Retry-After':'90'},None)
            with self.assertRaises(DeepLRateLimitError) as caught:request_json(url)
            self.assertEqual(caught.exception.retry_after,90)
            self.assertEqual(opener.return_value.open.call_count,1)
            opener.return_value.open.side_effect=urllib.error.HTTPError(url,456,'quota',{},None)
            with self.assertRaises(TranslationError) as caught:request_json(url)
            self.assertNotIsInstance(caught.exception,DeepLRateLimitError)

    def test_japanese_text_uses_language_detection(self):
        with patch('hoverling.translate.DEEPL_LIMITER',DeepLRequestLimiter()),patch('hoverling.translate.request_json',return_value={'translations':[{'text':'欢迎光临'}]}) as request:
            self.assertEqual(translate_deepl('いらっしゃいませ','placeholder:fx'),'欢迎光临')
            payload=request.call_args.args[1]
            self.assertEqual(payload['text'],['いらっしゃいませ'])
            self.assertNotIn('source_lang',payload)


if __name__=='__main__':unittest.main()
