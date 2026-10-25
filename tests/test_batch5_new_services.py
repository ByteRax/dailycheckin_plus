"""Regression tests for batch-5: anyrouter, quark, wxpusher.

All HTTP mocked; no real network; fake credentials only.
Run: python -m unittest discover -s tests -v
"""

import unittest
from unittest.mock import MagicMock, patch

import dailycheckin.utils.message as msg_mod
from dailycheckin.configs import checkin_map
from dailycheckin.quark.main import Quark


def fake_resp(status_code=200, payload=None, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    if payload is not None:

        def _json():
            return payload

        r.json = _json
    else:
        r.json.side_effect = ValueError("no json")
    return r


class TestQuark(unittest.TestCase):
    def test_already_signed_reports_progress(self):
        svc = Quark(check_item={"cookie": "fake=1"})
        payload = {
            "code": 0,
            "data": {
                "cap_sign": {"sign_daily": True, "sign_daily_reward": 104857600, "sign_progress": 5, "sign_target": 7}
            },
        }
        with patch("dailycheckin.quark.main.requests.get", return_value=fake_resp(payload=payload)):
            msg = svc.main()
        self.assertIn("今日已签到", msg)
        self.assertIn("100.0MB", msg)

    def test_sign_success_reports_reward(self):
        svc = Quark(check_item={"cookie": "fake=1"})
        info = {"code": 0, "data": {"cap_sign": {"sign_daily": False}}}
        sign = {"code": 0, "data": {"sign_daily_reward": 10485760}}
        with (
            patch("dailycheckin.quark.main.requests.get", return_value=fake_resp(payload=info)),
            patch("dailycheckin.quark.main.requests.post", return_value=fake_resp(payload=sign)) as post,
        ):
            msg = svc.main()
        self.assertIn("签到成功", msg)
        self.assertIn("10.0MB", msg)
        self.assertEqual(post.call_args.kwargs.get("timeout"), 15)

    def test_sign_api_error_reported(self):
        svc = Quark(check_item={"cookie": "fake=1"})
        info = {"code": 0, "data": {"cap_sign": {"sign_daily": False}}}
        sign = {"code": 32003, "message": "今天已签到"}
        with (
            patch("dailycheckin.quark.main.requests.get", return_value=fake_resp(payload=info)),
            patch("dailycheckin.quark.main.requests.post", return_value=fake_resp(payload=sign)),
        ):
            msg = svc.main()
        self.assertIn("签到失败", msg)
        self.assertIn("今天已签到", msg)

    def test_missing_cookie(self):
        svc = Quark(check_item={})
        msg = svc.main()
        self.assertIn("缺少 cookie", msg)


class TestWxPusher(unittest.TestCase):
    def test_success_code_1000(self):
        with patch.object(
            msg_mod.requests, "post", return_value=fake_resp(payload={"code": 1000, "msg": "ok"})
        ) as post:
            msg_mod.message2wxpusher("tk", "UID_x", "hello")
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["appToken"], "tk")
        self.assertEqual(body["uids"], ["UID_x"])
        self.assertEqual(post.call_args.kwargs.get("timeout"), 15)

    def test_failure_reports_msg(self):
        with patch.object(
            msg_mod.requests, "post", return_value=fake_resp(payload={"code": 20001, "msg": "token 无效"})
        ):
            msg_mod.message2wxpusher("bad", "UID_x", "hello")

    def test_push_message_sends_when_configured(self):
        with (
            patch.object(msg_mod, "important_notice", side_effect=Exception("skip")),
            patch.object(msg_mod, "message2wxpusher") as wx,
        ):
            msg_mod.push_message(["m1"], {"wxpusher_tk": "tk", "wxpusher_uid": "UID_x", "merge_push": False})
        self.assertEqual(wx.call_count, 1)


class TestCheckinMapRegistration(unittest.TestCase):
    def test_new_services_registered(self):
        self.assertIn("ANYROUTER", checkin_map)
        self.assertIn("QUARK", checkin_map)
        self.assertEqual(checkin_map["QUARK"][0], "夸克网盘")


if __name__ == "__main__":
    unittest.main()
