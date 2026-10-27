import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import server


class OptimizationTests(unittest.TestCase):
    def test_reject_invalid_inputs_before_api(self):
        for data in ({}, {'prompt': ' '}, {'prompt': 'a'*12001}, {'prompt':'valid','model':'x','scene':'unknown'}):
            with self.subTest(data=str(data)[:60]), patch('server.deepseek') as call:
                with self.assertRaises(server.APIError):
                    server.optimize(data)
                call.assert_not_called()

    def test_parse_result_and_preserve_constraints(self):
        content = {'prompt':'优化结果', 'changes':['明确目标'], 'questions':[]}
        response = {'choices':[{'message':{'content':json.dumps(content)}}], 'usage':{'total_tokens':50}}
        with patch('server.deepseek', return_value=response) as call:
            result = server.optimize({'prompt':'原始素材','model':'test','context':'输出中文'})
            self.assertEqual(result['prompt'], '优化结果')
            self.assertEqual(result['tokens'], 50)
            payload = call.call_args.args[1]
            self.assertIn('输出中文', payload['messages'][1]['content'])

    def test_malformed_and_truncated_response(self):
        for response in ({}, {'choices':[{'message':{'content':'not json'}}]}, {'choices':[{'finish_reason':'length'}]}):
            with patch('server.deepseek', return_value=response):
                with self.assertRaises(server.APIError):
                    server.optimize({'prompt':'test','model':'test'})


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.ThreadingHTTPServer(('127.0.0.1',0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_private_files_are_never_served(self):
        for path in ('/.env', '/server.py', '/static/../.env'):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(self.base + path)
            self.assertEqual(caught.exception.code, 404)

    def test_cross_origin_rejected(self):
        req = urllib.request.Request(self.base + '/api/status', headers={'Origin':'https://untrusted.example'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req)
        self.assertEqual(caught.exception.code, 403)

    def test_key_not_in_status(self):
        with patch('server.config', return_value={'DEEPSEEK_API_KEY':'sk-test-secret'}):
            with urllib.request.urlopen(self.base + '/api/status') as response:
                self.assertEqual(json.load(response), {'configured':True})


if __name__ == '__main__':
    unittest.main()
