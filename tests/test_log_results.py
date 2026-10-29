import argparse
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import dailycheckin.main as main


class ResultLoggingTests(unittest.TestCase):
    def run_service(self, service, account):
        args = argparse.Namespace(include=['TEST'], exclude=None, accounts=None)
        with patch.object(main, 'parse_arguments', return_value=args), \
             patch.object(main, 'checkin_map', {'TEST': ('测试', service)}), \
             patch.object(main, 'check_config', return_value=({}, {'test': [account]}, None, None)), \
             patch.object(main, 'push_message') as push, \
             patch.object(main.requests, 'get', side_effect=RuntimeError('offline')), \
             redirect_stdout(io.StringIO()) as output:
            main.checkin()
        return output.getvalue(), push.call_args.kwargs['content_list']

    def test_partial_result_and_secrets_are_redacted(self):
        class Service:
            outcome = 'partial'
            def __init__(self, item):
                pass
            def main(self):
                return '项目失败；test-secret cookie-value'
        output, notifications = self.run_service(Service, {'token': 'test-secret', 'cookie': 'sid=cookie-value'})
        self.assertIn('⚠️部分失败', output)
        self.assertIn('执行摘要', output)
        self.assertNotIn('test-secret', output + str(notifications))
        self.assertNotIn('cookie-value', output + str(notifications))

    def test_exception_keeps_existing_progress_in_log_and_notice(self):
        class Service:
            def __init__(self, item):
                self.messages = ['任务一已完成']
            def main(self):
                raise RuntimeError('连接失败')
        output, notifications = self.run_service(Service, {})
        for text in (output, str(notifications)):
            self.assertIn('任务一已完成', text)
            self.assertIn('连接失败', text)
            self.assertIn('❌失败', text)

    def test_legacy_service_not_marked_business_success(self):
        class Service:
            def __init__(self, item):
                pass
            def main(self):
                return '原有服务结果'
        output, _ = self.run_service(Service, {})
        self.assertIn('未判定业务结果', output)
        self.assertIn('原有服务结果', output)


if __name__ == '__main__':
    unittest.main()
