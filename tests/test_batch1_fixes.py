"""Regression tests for batch-1 fixes: bilibili / enshan / tieba.

All HTTP is mocked; no real network access; cookies are fake credentials.
Run: python -m unittest discover -s tests -v
"""

import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import requests

import dailycheckin.bilibili.main as bili_mod
from dailycheckin.bilibili.main import BiliBili
from dailycheckin.enshan.main import EnShan
from dailycheckin.tieba.main import Tieba


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def make_session(payload):
    s = MagicMock()
    s.get.return_value = FakeResponse(payload)
    s.post.return_value = FakeResponse(payload)
    return s


class TestBilibili(unittest.TestCase):
    def test_get_region_uses_newlist_and_tolerates_null(self):
        session = make_session({"code": -404, "data": None})
        result = BiliBili.get_region(session=session)
        self.assertEqual(result, [])
        url = session.get.call_args.kwargs.get("url") or session.get.call_args[0][0]
        self.assertIn("/x/web-interface/newlist", url)

    def test_get_region_parses_archives(self):
        payload = {"code": 0, "data": {"archives": [{"aid": 1, "cid": 2, "title": "t", "owner": {"name": "u"}}]}}
        result = BiliBili.get_region(session=make_session(payload))
        self.assertEqual(result[0]["aid"], 1)

    def test_space_arc_search_null_safe(self):
        result, count = BiliBili.space_arc_search(session=make_session({"code": -404, "data": None}), uid=1)
        self.assertEqual(result, [])
        self.assertEqual(count, 2)

    def test_get_today_exp_null_safe(self):
        result = BiliBili.get_today_exp(session=make_session({"code": 0, "data": None}))
        self.assertEqual(result, [])

    def test_live_status_null_safe(self):
        result = BiliBili.live_status(session=make_session({"code": 0, "data": None}))
        self.assertEqual([r["value"] for r in result], [0, 0, 0])

    def test_main_returns_msg_when_not_login(self):
        fake_cookie = "SESSDATA=fake; bili_jct=fakejct"
        with patch.object(BiliBili, "get_nav", return_value=("u", 1, 0, 50, 0, 0)):
            msg = BiliBili(check_item={"cookie": fake_cookie}).main()
        self.assertIsInstance(msg, str)
        self.assertIn("cookie", msg.lower())

    def test_coin_add_sleeps_between_successes(self):
        fake_cookie = "SESSDATA=fake; bili_jct=fakejct"
        nav = ("user", 1, 1, 50, 0, 0)
        aid_list = [{"aid": 1, "cid": 1, "title": "a", "owner": "x"}, {"aid": 2, "cid": 2, "title": "b", "owner": "y"}]
        sleeps = []
        patchers = [
            patch.object(BiliBili, "get_nav", return_value=nav),
            patch.object(BiliBili, "manga_sign", return_value="ok"),
            patch.object(BiliBili, "live_sign", return_value="ok"),
            patch.object(BiliBili, "get_region", return_value=aid_list),
            patch.object(BiliBili, "vip_privilege_my", return_value={"data": {"list": []}}),
            patch.object(BiliBili, "get_today_exp", return_value=[]),
            patch.object(BiliBili, "coin_add", side_effect=[{"code": 0}, {"code": 0}]),
            patch.object(BiliBili, "report_task", return_value={"code": 0}),
            patch.object(BiliBili, "share_task", return_value={"code": 0}),
            patch.object(BiliBili, "live_status", return_value=[]),
            patch.object(bili_mod.time, "sleep", side_effect=sleeps.append),
        ]
        with ExitStack() as stack:
            for p in patchers:
                stack.enter_context(p)
            msg = BiliBili(check_item={"cookie": fake_cookie, "coin_num": 2, "coin_type": 0}).main()
        self.assertIn("今日成功投币2/2", msg)
        self.assertEqual(len(sleeps), 1, "two successful coin adds must sleep once in between")


class TestEnShan(unittest.TestCase):
    def test_get_info_tolerates_521(self):
        session = MagicMock()
        session.get.return_value = FakeResponse({}, status_code=521, text="")
        result = EnShan.get_info(session=session)
        self.assertEqual(len(result), 1)
        self.assertIn("获取失败", result[0]["value"])

    def test_get_info_parses_credit(self):
        html = "xx恩山币: </em>123&nbsp;<em>积分: </em>456<span"
        session = MagicMock()
        session.get.return_value = FakeResponse({}, status_code=200, text=html)
        result = EnShan.get_info(session=session)
        self.assertEqual(result[0]["value"], "123")
        self.assertEqual(result[1]["value"], "456")

    def test_get_info_no_raise_on_http_error(self):
        session = MagicMock()
        session.get.return_value = FakeResponse({}, status_code=500, text="")
        try:
            result = EnShan.get_info(session=session)
            self.assertIsInstance(result, list)
        except Exception:
            self.fail("get_info must not raise on HTTP errors")

    def test_main_returns_msg_when_formhash_fails(self):
        session = MagicMock()
        session.get.return_value = FakeResponse({}, status_code=521, text="")
        with patch("dailycheckin.enshan.main.requests.Session", return_value=session):
            msg = EnShan(check_item={"cookie": "fake=1"}).main()
        self.assertIn("formhash", msg)


class TestTieba(unittest.TestCase):
    def test_sign_url_uses_new_domain(self):
        t = Tieba(check_item={"cookie": "BDUSS=fakebduss"})
        self.assertTrue(t.SIGN_URL.startswith("https://tiebac.baidu.com/"))


if __name__ == "__main__":
    unittest.main()
