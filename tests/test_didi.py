import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from dailycheckin.configs import checkin_map, get_checkin_info
from dailycheckin.didi.main import Didi
from dailycheckin.didi.client import DiDiWelfare


class DidiTests(unittest.TestCase):
    def setUp(self):
        network = patch("socket.socket.connect", side_effect=AssertionError("network is forbidden"))
        network.start()
        self.addCleanup(network.stop)

    def test_registered(self):
        self.assertIn("DIDI", checkin_map)

    def test_missing_token_is_rejected_before_running(self):
        for account in ({}, {"token": ""}, {"account_name": "测试"}):
            with self.subTest(account=account), patch("dailycheckin.didi.main.DiDiWelfare") as welfare:
                with self.assertRaises((ValueError, KeyError)):
                    Didi(account).main()
                welfare.assert_not_called()

    def test_main_runs_welfare_with_token(self):
        with patch("dailycheckin.didi.main.DiDiWelfare") as welfare:
            welfare.return_value.run = AsyncMock(return_value="完成")
            welfare.return_value.messages = ["完成"]
            Didi({"token": "test-token", "account_name": "测试"}).main()
            welfare.assert_called_once_with("测试#test-token")
            welfare.return_value.run.assert_awaited_once_with()

    def test_environment_accounts_and_explicit_precedence(self):
        expected = [{"account_name": "甲", "token": "token-one"}, {"token": "token-two"}]
        with patch.dict("os.environ", {"DD_TOKENS": "甲#token-one&token-two"}, clear=True):
            for data in (None, {}):
                with self.subTest(data=data):
                    self.assertEqual(get_checkin_info(data)["didi"], expected)
            configured = [{"token": "configured", "account_name": "指定"}]
            self.assertEqual(get_checkin_info({"DIDI": configured})["didi"], configured)

    def test_tls_verification_enabled(self):
        with patch("dailycheckin.didi.client.httpx.AsyncClient") as client:
            DiDiWelfare("test-token")
            self.assertIsNot(client.call_args.kwargs.get("verify", True), False)

    def test_divide_and_legacy_do_not_call_insurance(self):
        with patch("dailycheckin.didi.client.httpx.AsyncClient"), \
             patch("dailycheckin.didi.client.do_divide", True), \
             patch("dailycheckin.didi.client.do_legacy", True), \
             patch("dailycheckin.didi.client.asyncio.sleep", new_callable=AsyncMock):
            runner = DiDiWelfare("test-token")
            with patch.object(runner, "_safe", wraps=runner._safe) as safe, \
                 patch.object(runner, "run_divide", new_callable=AsyncMock) as divide, \
                 patch.object(runner, "receive_level_gift", new_callable=AsyncMock) as gift, \
                 patch.object(runner, "receive_privilege", new_callable=AsyncMock) as privilege:
                asyncio.run(runner._run_divide_and_legacy())
            self.assertEqual([call.args[0] for call in safe.call_args_list],
                             ["瓜分福利金", "等级礼券", "周三折上折"])
            divide.assert_awaited_once()
            gift.assert_awaited_once()
            privilege.assert_awaited_once()
            self.assertNotIn("保险", str(privilege.call_args))
            self.assertNotIn("insurance", str(privilege.call_args).lower())

    def test_actual_main_orchestrates_and_closes_client(self):
        with patch("dailycheckin.didi.client.httpx.AsyncClient") as client, \
             patch("dailycheckin.didi.client._CHECK_MODE", False), \
             patch("dailycheckin.didi.client.do_record", False), \
             patch.object(DiDiWelfare, "fetch_profile", new_callable=AsyncMock) as profile, \
             patch.object(DiDiWelfare, "fetch_bonus", new_callable=AsyncMock, side_effect=[10, 12]) as bonus, \
             patch.object(DiDiWelfare, "_run_tasks", new_callable=AsyncMock) as tasks, \
             patch.object(DiDiWelfare, "_run_divide_and_legacy", new_callable=AsyncMock) as divide, \
             patch.object(DiDiWelfare, "_run_janitor_and_pick", new_callable=AsyncMock) as janitor:
            client.return_value.aclose = AsyncMock()
            result = Didi({"token": "test-token", "account_name": "测试"}).main()
            profile.assert_awaited_once()
            self.assertEqual(bonus.await_count, 2)
            tasks.assert_awaited_once()
            divide.assert_awaited_once()
            janitor.assert_awaited_once()
            client.return_value.aclose.assert_awaited_once()
            self.assertIn("10→12", result)
            self.assertNotIn("test-token", result)

    def test_outcome_matches_runner_errors_and_expired_token(self):
        for ok, warn, err, dead, expected in [(0, 0, 0, True, "failed"), (0, 0, 1, False, "failed"), (1, 0, 1, False, "partial"), (1, 1, 0, False, "partial"), (1, 0, 0, False, "success")]:
            with self.subTest(expected=expected), patch("dailycheckin.didi.main.DiDiWelfare") as cls:
                runner = cls.return_value
                runner.run = AsyncMock()
                runner.messages = []
                runner.ok, runner.warn, runner.err, runner.token_dead = ok, warn, err, dead
                service = Didi({"token": "test-token"})
                service.main()
                self.assertEqual(service.outcome, expected)

    def test_empty_environment_has_no_accounts(self):
        with patch.dict("os.environ", {"DD_TOKENS": ""}, clear=True):
            self.assertEqual(get_checkin_info({})["didi"], [])


if __name__ == "__main__":
    unittest.main()
