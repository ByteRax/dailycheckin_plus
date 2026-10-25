"""Regression tests for batch-4: --accounts, mimotion token persistence, niu service.

All HTTP mocked; no real network; fake credentials only.
Run: python -m unittest discover -s tests -v
"""

import base64
import json
import os
import tempfile
import time as _time
import unittest
from unittest.mock import MagicMock, patch

import dailycheckin.main as dc_main
from dailycheckin.main import parse_account_range
from dailycheckin.mimotion.main import MiMotion
from dailycheckin.niu.main import Niu


class TestAccountRange(unittest.TestCase):
    def test_parse_valid(self):
        self.assertEqual(parse_account_range("0-1"), (0, 1))
        self.assertEqual(parse_account_range(" 2-4 "), (2, 4))
        self.assertIsNone(parse_account_range(None))
        self.assertIsNone(parse_account_range(""))

    def test_parse_invalid(self):
        self.assertIsNone(parse_account_range("abc"))
        self.assertIsNone(parse_account_range("5-2"))
        self.assertIsNone(parse_account_range("0;1"))
        self.assertIsNone(parse_account_range("-1"))

    def test_checkin_applies_account_slice(self):
        calls = []

        class FakeService:
            def __init__(self, check_item):
                calls.append(check_item)

            def main(self):
                return "ok"

        accounts = [{"id": i} for i in range(5)]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            data = {"TESTSVC": accounts}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            with (
                patch.object(os, "getcwd", return_value=tmp),
                patch.object(dc_main, "checkin_map", {"TESTSVC": ("测试", FakeService)}),
                patch.object(
                    dc_main, "get_checkin_info", side_effect=lambda data: {"testsvc": data.get("TESTSVC", [])}
                ),
                patch.object(dc_main, "get_notice_info", side_effect=lambda data: {}),
                patch.object(dc_main, "push_message"),
                patch.object(dc_main.requests, "get", side_effect=Exception("no network")),
                patch("sys.argv", ["dailycheckin", "--accounts", "1-2"]),
            ):
                dc_main.checkin()
        self.assertEqual(len(calls), 2)
        self.assertEqual([c["id"] for c in calls], [1, 2])


class FakeMiResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class TestMiMotion(unittest.TestCase):
    def _svc(self, item):
        return MiMotion(check_item=item)

    def test_cached_token_used_and_persisted(self):
        svc = self._svc({"phone": "13812345678", "password": "pw", "user": "111", "app_token": "tok"})
        with (
            patch.object(svc, "get_time", return_value=1),
            patch.object(svc, "login", side_effect=self._fail_login) as login,
            patch("dailycheckin.mimotion.main.requests.post", return_value=FakeMiResponse({"message": "Success"})),
        ):
            msg = svc.main()
        self.assertIn("Success", msg)
        login.assert_not_called()
        self.assertEqual(svc.check_item["user"], "111")
        self.assertEqual(svc.check_item["app_token"], "tok")

    def test_cached_token_failure_falls_back_to_login(self):
        svc = self._svc({"phone": "13812345678", "password": "pw", "user": "111", "app_token": "dead"})
        responses = [FakeMiResponse({"message": "error"})]

        def post_side_effect(url, **kwargs):
            if "band_data" in url:
                return responses.pop(0) if responses else FakeMiResponse({"message": "Success"})
            return FakeMiResponse({})

        def login_ok(phone, password):
            return "lt", "222", "fresh"

        with (
            patch.object(svc, "get_time", return_value=1),
            patch.object(svc, "login", side_effect=login_ok) as login,
            patch("dailycheckin.mimotion.main.requests.post", side_effect=post_side_effect),
        ):
            msg = svc.main()
        self.assertIn("Success", msg)
        login.assert_called_once()
        self.assertEqual(svc.check_item["user"], "222")
        self.assertEqual(svc.check_item["app_token"], "fresh")

    def test_no_cache_logs_in(self):
        svc = self._svc({"phone": "13812345678", "password": "pw"})

        def login_ok(phone, password):
            return "lt", "333", "tok3"

        with (
            patch.object(svc, "get_time", return_value=1),
            patch.object(svc, "login", side_effect=login_ok) as login,
            patch("dailycheckin.mimotion.main.requests.post", return_value=FakeMiResponse({"message": "Success"})),
        ):
            svc.main()
        login.assert_called_once()
        self.assertEqual(svc.check_item["app_token"], "tok3")

    @staticmethod
    def _fail_login(phone, password):
        return 0, 0, "获取token失败"


class TestNiu(unittest.TestCase):
    def _svc(self, tmp_state_file):
        return Niu(check_item={"account": "13800000000", "password": "0" * 32, "state_file": tmp_state_file})

    def test_token_persisted_and_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = os.path.join(tmp, "niu_token.json")
            svc = self._svc(state_file)
            token_resp = {
                "status": 0,
                "data": {"token": {"access_token": "a." + "x" * 20 + "." + "y", "refresh_token": "r1"}},
            }

            def fake_oauth(params):
                return token_resp

            # JWT exp in future: craft token with exp far ahead
            payload = base64.urlsafe_b64encode(json.dumps({"exp": int(_time.time()) + 86400 * 30}).encode()).decode()
            token_resp["data"]["token"]["access_token"] = f"hdr.{payload}.sig"
            with patch.object(svc, "_oauth", side_effect=fake_oauth) as oauth:
                tok = svc._ensure_token({})
                tok2 = svc._ensure_token(json.load(open(state_file))["13800000000"])
            oauth.assert_called_once()
            self.assertEqual(tok, tok2)
            state = json.load(open(state_file))
            self.assertEqual(state["13800000000"]["access_token"], tok)

    def test_main_shares_posts_and_reports_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = os.path.join(tmp, "state.json")
            svc = self._svc(state_file)

            payload = base64.urlsafe_b64encode(json.dumps({"exp": int(_time.time()) + 86400 * 30}).encode()).decode()
            fixed_token = f"hdr.{payload}.sig"

            with (
                patch.object(svc, "_ensure_token", return_value=fixed_token),
                patch.object(svc, "_points", side_effect=[100, 110]),
                patch.object(svc, "_get_posts", return_value=[{"id": 1}, {"id": 2}, {"id": 3}]),
                patch.object(svc, "_share", return_value={"status": 0}),
                patch("dailycheckin.niu.main.time.sleep"),
            ):
                msg = svc.main()
            self.assertIn("138****0000", msg)
            self.assertIn("+10", msg)


if __name__ == "__main__":
    unittest.main()
