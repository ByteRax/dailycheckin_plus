import io
import json
import logging
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from dailycheckin import CheckIn
from dailycheckin.configs import get_checkin_info
from dailycheckin.wps.main import WPS


class WPSTests(unittest.TestCase):
    def setUp(self):
        self.account = {
            "user_id": 123,
            "cookies": "uid=123; wps_sid=test-secret",
            "max_lottery_limit": 2,
        }
        self.network = patch("socket.socket.connect", side_effect=AssertionError("network is forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        task_patch = patch("dailycheckin.wps.main.WPSTaskCenterPage")
        benefit_patch = patch("dailycheckin.wps.main.DailyBenefitsTasks")
        self.task_class = task_patch.start()
        self.benefit_class = benefit_patch.start()
        self.addCleanup(task_patch.stop)
        self.addCleanup(benefit_patch.stop)
        self.task = self.task_class.return_value
        self.benefit = self.benefit_class.return_value
        self.task_result = {"success": True, "auth_expired": False, "message": "签到成功"}
        self.benefit_result = {"success": True, "auth_expired": False, "message": "福利完成"}
        self.task.process_account.return_value = self.task_result
        self.benefit.process_account.return_value = self.benefit_result
        self.task_class.build_notification_lines.return_value = ["任务中心成功"]
        self.benefit_class.build_notification_lines.return_value = ["福利成功"]
        self.task.build_notification_lines.return_value = ["任务中心成功"]
        self.benefit.build_notification_lines.return_value = ["福利成功"]

    def assert_page_options(self, page_class):
        self.assertEqual(page_class.call_count, 1)
        kwargs = page_class.call_args.kwargs
        self.assertIs(kwargs.get("enable_notification"), False)
        self.assertIs(kwargs.get("load_accounts"), False)

    def assert_account_forwarded(self, page):
        page.process_account.assert_called_once()
        account = page.process_account.call_args.args[0]
        for key, value in self.account.items():
            self.assertEqual(account[key], value)

    def assert_lines_built(self, page_class, page, result):
        calls = page_class.build_notification_lines.call_args_list + page.build_notification_lines.call_args_list
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[0], result)

    def test_missing_credentials_rejected_before_processing(self):
        for account in ({}, {"user_id": 123}, {"cookies": "uid=123; wps_sid=test-secret"}):
            with self.subTest(account=account):
                with self.assertRaises(ValueError):
                    WPS(account).main()
        self.task.process_account.assert_not_called()
        self.benefit.process_account.assert_not_called()

    def test_success_processes_and_formats_both_pages(self):
        client = WPS(self.account)
        self.assertIsInstance(client, CheckIn)
        client.main()
        self.assert_page_options(self.task_class)
        self.assert_page_options(self.benefit_class)
        self.assert_account_forwarded(self.task)
        self.assert_account_forwarded(self.benefit)
        self.assert_lines_built(self.task_class, self.task, self.task_result)
        self.assert_lines_built(self.benefit_class, self.benefit, self.benefit_result)

    def test_non_auth_failure_still_processes_second_page(self):
        self.task_result.update(success=False, message="任务中心失败")
        WPS(self.account).main()
        self.assert_account_forwarded(self.task)
        self.assert_account_forwarded(self.benefit)
        self.assert_lines_built(self.task_class, self.task, self.task_result)
        self.assert_lines_built(self.benefit_class, self.benefit, self.benefit_result)

    def test_second_page_failure_is_formatted(self):
        self.benefit_result.update(success=False, message="福利失败")
        WPS(self.account).main()
        self.assert_account_forwarded(self.benefit)
        self.assert_lines_built(self.benefit_class, self.benefit, self.benefit_result)

    def test_expired_auth_skips_second_page(self):
        self.task_result.update(success=False, auth_expired=True, message="登录已失效")
        WPS(self.account).main()
        self.assert_account_forwarded(self.task)
        self.assert_lines_built(self.task_class, self.task, self.task_result)
        self.benefit.process_account.assert_not_called()
        self.benefit_class.build_notification_lines.assert_not_called()
        self.benefit.build_notification_lines.assert_not_called()

class WPSOutcomeAndLoggingTests(unittest.TestCase):
    def test_outcomes_and_return_value(self):
        account = {"user_id": 123, "cookies": "sid=test"}
        cases = [
            (True, True, False, "success"),
            (False, True, False, "partial"),
            (True, False, False, "partial"),
            (False, False, False, "failed"),
            (True, False, True, "failed"),
        ]
        with patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            for first, second, expired, expected in cases:
                with self.subTest(first=first, second=second, expired=expired):
                    with patch("dailycheckin.wps.main.WPSTaskCenterPage") as task, patch(
                        "dailycheckin.wps.main.DailyBenefitsTasks"
                    ) as benefits:
                        task.return_value.process_account.return_value = {"success": first}
                        benefits.return_value.process_account.return_value = {
                            "success": second, "auth_expired": expired
                        }
                        task.return_value.build_notification_lines.return_value = ["任务"]
                        benefits.return_value.build_notification_lines.return_value = ["福利"]
                        client = WPS(account)
                        output = client.main()
                        self.assertEqual(client.outcome, expected)
                        self.assertEqual(output, "任务\n福利" + (
                            "\n登录态失效，已停止后续任务" if expired else ""
                        ))

    def test_failed_lottery_marks_partial(self):
        with patch("dailycheckin.wps.main.WPSTaskCenterPage") as task, patch(
            "dailycheckin.wps.main.DailyBenefitsTasks"
        ) as benefits:
            task.return_value.process_account.return_value = {
                "success": True, "lottery_info": {"results": [{"success": False}]}
            }
            benefits.return_value.process_account.return_value = {"success": True}
            task.return_value.build_notification_lines.return_value = []
            benefits.return_value.build_notification_lines.return_value = []
            client = WPS({"user_id": 123, "cookies": "sid=test"})
            client.main()
            self.assertEqual(client.outcome, "partial")

    def test_logging_to_stdout_without_changing_root_or_duplicating(self):
        from dailycheckin.wps.logging_utils import configure_logging, get_logger

        logger = logging.getLogger("wps")
        old_handlers, old_level, old_propagate = logger.handlers[:], logger.level, logger.propagate
        root = logging.getLogger()
        root_state = (root.level, root.handlers[:], [(h.level, h.formatter) for h in root.handlers])
        output = io.StringIO()
        try:
            logger.handlers = []
            with redirect_stdout(output):
                configure_logging()
                configure_logging()
                get_logger("test").info("WPS 正常日志")
            self.assertEqual(output.getvalue().count("WPS 正常日志"), 1)
            self.assertEqual(len(logger.handlers), 1)
            self.assertEqual(root_state, (root.level, root.handlers[:], [(h.level, h.formatter) for h in root.handlers]))
        finally:
            for handler in logger.handlers:
                handler.close()
            logger.handlers = old_handlers
            logger.setLevel(old_level)
            logger.propagate = old_propagate


class WPSPageIntegrationTests(unittest.TestCase):
    def test_cookie_parsers_accept_whitespace_and_embedded_equals(self):
        from dailycheckin.wps.api import WPSAPI
        from dailycheckin.wps.daily_benefits import DailyBenefitsAPI

        for api in (WPSAPI, DailyBenefitsAPI):
            self.assertEqual(api._parse_cookies('uid=123;wps_sid=a=b; x=y'),
                             {'uid': '123', 'wps_sid': 'a=b', 'x': 'y'})

    @patch('dailycheckin.wps.task_center.time.sleep')
    @patch('dailycheckin.wps.task_center.WPSAPI')
    def test_task_center_respects_lottery_limit(self, api_class, sleep):
        from dailycheckin.wps.task_center import WPSTaskCenterPage

        api = api_class.return_value
        api.sign_in.return_value = {'success': True, 'already_signed': True}
        api.get_user_info.return_value = {'success': True, 'lottery_times': 6}
        api.lottery.return_value = {'success': True, 'prize_name': '积分'}
        result = WPSTaskCenterPage(load_accounts=False, enable_notification=False).process_account(
            {'user_id': 123, 'cookies': 'uid=123', 'max_lottery_limit': 2}
        )
        self.assertTrue(result['success'])
        self.assertEqual(api.lottery.call_count, 2)
        self.assertEqual(result['lottery_info']['successful_draws'], 2)

    @patch('dailycheckin.wps.task_center.WPSAPI')
    def test_task_center_expired_login_stops_followup_requests(self, api_class):
        from dailycheckin.wps.task_center import WPSTaskCenterPage

        api = api_class.return_value
        api.sign_in.return_value = {'success': False, 'error_type': 'token_expired'}
        result = WPSTaskCenterPage(load_accounts=False, enable_notification=False).process_account(
            {'user_id': 123, 'cookies': 'uid=123'}
        )
        self.assertTrue(result['auth_expired'])
        api.get_user_info.assert_not_called()
        api.lottery.assert_not_called()

    @patch('dailycheckin.wps.daily_benefits.DailyBenefitsAPI')
    def test_benefits_invalid_login_stops_immediately(self, api_class):
        from dailycheckin.wps.daily_benefits import DailyBenefitsTasks
        api = api_class.return_value
        api.get_benefit_portal.return_value = {'success': False, 'error': '未登录', 'error_type': 'token_expired'}
        result = DailyBenefitsTasks(load_accounts=False, enable_notification=False).process_account({'cookies': 'x=y'})
        self.assertTrue(result['auth_expired'])
        api.get_page_info.assert_not_called()

    @patch('dailycheckin.wps.daily_benefits.DailyBenefitsAPI')
    def test_benefits_network_failure_does_not_run_actions(self, api_class):
        from dailycheckin.wps.daily_benefits import DailyBenefitsTasks
        api = api_class.return_value
        api.get_benefit_portal.return_value = {'success': False, 'error': '网络异常'}
        result = DailyBenefitsTasks(load_accounts=False, enable_notification=False).process_account({'cookies': 'x=y'})
        self.assertFalse(result['success'])
        api.get_page_info.assert_not_called()


class WPSEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.account = {"user_id": 123, "cookies": "wps_sid=test-secret"}
        network = patch("socket.socket.connect", side_effect=AssertionError("network is forbidden"))
        network.start()
        self.addCleanup(network.stop)

    def test_environment_json_formats_and_names(self):
        accounts = [self.account]
        for name in ("WPS", "wps"):
            for value in ({"wps": {"accounts": accounts}}, {"accounts": accounts}, accounts):
                for data in ({}, {"WPS": []}, None):
                    with self.subTest(name=name, value=value, data=data):
                        with patch.dict("os.environ", {name: json.dumps(value)}, clear=True):
                            self.assertEqual(get_checkin_info(data)["wps"], accounts)

    def test_fragment_and_uppercase_precedence(self):
        fragment = json.dumps({"wps": {"accounts": [self.account]}})[1:-1]
        with patch.dict("os.environ", {"WPS": fragment, "wps": json.dumps([])}, clear=True):
            self.assertEqual(get_checkin_info({})["wps"], [self.account])

    def test_nonempty_config_takes_precedence_over_environment(self):
        configured = [{"user_id": 456, "cookies": "wps_sid=config-secret"}]
        for name in ("WPS", "wps"):
            with self.subTest(name=name), patch.dict(
                "os.environ", {name: json.dumps({"accounts": [self.account]})}, clear=True
            ):
                self.assertEqual(get_checkin_info({"WPS": configured})["wps"], configured)

    def test_invalid_json_is_empty_and_does_not_print_sensitive_value(self):
        secret = "wps_sid=private-secret"
        for name in ("WPS", "wps"):
            for data in ({}, None):
                with self.subTest(name=name, data=data):
                    output = io.StringIO()
                    with patch.dict("os.environ", {name: '{"accounts": "' + secret}, clear=True):
                        with redirect_stdout(output), redirect_stderr(output):
                            result = get_checkin_info(data)
                    self.assertEqual(result["wps"], [])
                    self.assertNotIn(secret, output.getvalue())


if __name__ == "__main__":
    unittest.main()
