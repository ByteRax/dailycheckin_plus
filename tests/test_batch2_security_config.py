"""Regression tests for batch-2: baiduwp cookie refresh, config save, imaotai mask, message fixes.

All HTTP and filesystem writes are mocked or isolated to a temp dir; no real network access.
Run: python -m unittest discover -s tests -v
"""

import json
import os
import stat
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import dailycheckin.main as dc_main
from dailycheckin.baiduwp.main import BaiduWP
from dailycheckin.imaotai.main import IMAOTAI
from dailycheckin.utils import message as msg_mod


class FakeSetCookie:
    def __init__(self, name, value, expires=None):
        self.name = name
        self.value = value
        self.expires = expires
        self.domain = ".baidu.com"
        self.path = "/"


class FakeBaiduResp:
    def __init__(self, status_code=200, text="", cookies=()):
        self.status_code = status_code
        self.text = text
        self.cookies = list(cookies)


class TestBaiduWP(unittest.TestCase):
    def test_parse_cookie(self):
        parsed = BaiduWP._parse_cookie("a=1; b = 2 ;c; =3; d=4=5")
        self.assertEqual(parsed, {"a": "1", "b": "2", "d": "4=5"})

    def test_init_sets_session_cookies(self):
        s = BaiduWP(check_item={"cookie": "STOKEN=fake; BDCLND=fake2"})
        names = [c.name for c in s.session.cookies]
        self.assertIn("STOKEN", names)
        self.assertIn("BDCLND", names)

    def test_get_updates_check_item_cookie(self):
        item = {"cookie": "STOKEN=old"}
        s = BaiduWP(check_item=item)
        resp = FakeBaiduResp(cookies=[FakeSetCookie("STOKEN", "newvalue")])
        with patch.object(s.session, "get", return_value=resp):
            s._get("https://pan.baidu.com/x")
        self.assertEqual(item["cookie"], "STOKEN=newvalue")

    def test_get_removes_expired_cookie(self):
        item = {"cookie": "STOKEN=old"}
        s = BaiduWP(check_item=item)
        resp = FakeBaiduResp(cookies=[FakeSetCookie("STOKEN", "x", expires=1)])
        with patch.object(s.session, "get", return_value=resp):
            s._get("https://pan.baidu.com/x")
        self.assertEqual(item["cookie"], "")

    def test_signin_error_msg_has_no_cookie(self):
        s = BaiduWP(check_item={"cookie": "STOKEN=secret_value"})
        resp = FakeBaiduResp(status_code=521)
        with patch.object(s.session, "get", return_value=resp):
            _, err = s.signin()
        self.assertNotIn("secret_value", err)
        self.assertIn("521", err)


class TestSaveConfig(unittest.TestCase):
    def test_save_config_atomic_write_and_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"BAIDUWP": [{"cookie": "old"}]}, f, ensure_ascii=False, indent=4)
            os.chmod(path, 0o600)
            data = {"BAIDUWP": [{"cookie": "new"}]}
            self.assertTrue(dc_main.save_config(path, data))
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), data)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_save_config_failure_keeps_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"a": 1}, f)

            # data containing a non-serializable object forces a failure
            class Obj:
                pass

            self.assertFalse(dc_main.save_config(path, {"b": Obj()}))
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"a": 1})


class TestCheckinWriteback(unittest.TestCase):
    def test_checkin_persists_changed_check_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            data = {"BAIDUWP": [{"cookie": "before"}]}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)

            captured = {}

            class FakeService:
                def __init__(self, check_item):
                    captured["item"] = check_item

                def main(self):
                    captured["item"]["cookie"] = "after"
                    return "ok"

            with (
                patch.object(os, "getcwd", return_value=tmp),
                patch.object(dc_main, "checkin_map", {"BAIDUWP": ("百度网盘", FakeService)}),
                patch.object(
                    dc_main, "get_checkin_info", side_effect=lambda data: {"baiduwp": data.get("BAIDUWP", [])}
                ),
                patch.object(dc_main, "get_notice_info", side_effect=lambda data: {}),
                patch.object(dc_main, "push_message"),
                patch.object(dc_main.requests, "get", side_effect=Exception("no network")),
                patch("sys.argv", ["dailycheckin"]),
            ):
                dc_main.checkin()
            self.assertEqual(captured["item"]["cookie"], "after")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["BAIDUWP"][0]["cookie"], "after")


class TestImaoTai(unittest.TestCase):
    def test_mask_mobile(self):
        self.assertEqual(IMAOTAI.mask_mobile("13812345678"), "138****5678")
        self.assertEqual(IMAOTAI.mask_mobile("12345"), "12345")
        self.assertEqual(IMAOTAI.mask_mobile(None), "")

    def test_init_retries_itunes_and_falls_back(self):
        with patch("dailycheckin.imaotai.main.requests.get", side_effect=Exception("network down")):
            svc = IMAOTAI(check_item={"mobile": "13812345678", "token": "t", "userid": "u"})
        self.assertEqual(svc.mt_version, "1.3.7")


class TestMessage(unittest.TestCase):
    def test_message2server_uses_sctapi(self):
        with patch("dailycheckin.utils.message.requests.post") as post:
            msg_mod.message2server("fakekey", "hello")
            url = post.call_args.kwargs.get("url") or post.call_args[0][1]
        self.assertTrue(url.startswith("https://sctapi.ftqq.com/"))

    def test_message2server_turbo_sc3(self):
        with patch("dailycheckin.utils.message.requests.post") as post:
            msg_mod.message2server_turbo("sctp3tFakeKey", "hello")
            url = post.call_args.kwargs.get("url") or post.call_args[0][1]
        self.assertIn("push.ft07.com", url)

    def test_qywx_app_long_content_uses_text(self):
        long_content = "长" * 300  # 600 utf-8 bytes > 512
        get = patch("dailycheckin.utils.message.requests.get")
        post = patch("dailycheckin.utils.message.requests.post")
        with get as get_mock, post as post_mock:
            get_mock.return_value.json.return_value = {"access_token": "fake"}
            msg_mod.message2qywxapp(
                qywx_corpid="c",
                qywx_agentid="1000002",
                qywx_corpsecret="s",
                qywx_touser="u",
                qywx_media_id=None,
                qywx_origin=None,
                content=long_content,
            )
            payload = json.loads(post_mock.call_args.kwargs.get("data") or post.call_args[1][1])
        self.assertEqual(payload["msgtype"], "text")
        self.assertEqual(payload["text"]["content"], long_content)

    def test_qywx_app_oversize_content_truncated(self):
        huge_content = "长" * 1500  # 4500 utf-8 bytes > 2048 text limit
        get = patch("dailycheckin.utils.message.requests.get")
        post = patch("dailycheckin.utils.message.requests.post")
        with get as get_mock, post as post_mock:
            get_mock.return_value.json.return_value = {"access_token": "fake"}
            msg_mod.message2qywxapp(
                qywx_corpid="c",
                qywx_agentid="1000002",
                qywx_corpsecret="s",
                qywx_touser="u",
                qywx_media_id=None,
                qywx_origin=None,
                content=huge_content,
            )
            payload = json.loads(post_mock.call_args.kwargs.get("data") or post.call_args[1][1])
        self.assertEqual(payload["msgtype"], "text")
        self.assertLessEqual(len(payload["text"]["content"].encode("utf-8")), 2048)
        self.assertIn("截断", payload["text"]["content"])

    def test_qywx_media_id_still_uses_mpnews(self):
        get = patch("dailycheckin.utils.message.requests.get")
        post = patch("dailycheckin.utils.message.requests.post")
        with get as get_mock, post as post_mock:
            get_mock.return_value.json.return_value = {"access_token": "fake"}
            msg_mod.message2qywxapp(
                qywx_corpid="c",
                qywx_agentid="1000002",
                qywx_corpsecret="s",
                qywx_touser="u",
                qywx_media_id="fake_media",
                qywx_origin=None,
                content="任意内容",
            )
            payload = json.loads(post_mock.call_args.kwargs.get("data") or post.call_args[1][1])
        self.assertEqual(payload["msgtype"], "mpnews")

    def test_qywx_app_short_content_uses_textcard(self):
        get = patch("dailycheckin.utils.message.requests.get")
        post = patch("dailycheckin.utils.message.requests.post")
        with get as get_mock, post as post_mock:
            get_mock.return_value.json.return_value = {"access_token": "fake"}
            msg_mod.message2qywxapp(
                qywx_corpid="c",
                qywx_agentid="1000002",
                qywx_corpsecret="s",
                qywx_touser="u",
                qywx_media_id=None,
                qywx_origin=None,
                content="短内容",
            )
            payload = json.loads(post_mock.call_args.kwargs.get("data") or post.call_args[1][1])
        self.assertEqual(payload["msgtype"], "textcard")


if __name__ == "__main__":
    unittest.main()
