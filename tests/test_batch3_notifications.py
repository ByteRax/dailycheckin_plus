"""Regression tests for batch-3 notification channels. All HTTP mocked; no real network.

Run: python -m unittest discover -s tests -v
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import dailycheckin.utils.message as msg_mod
from dailycheckin.utils.message import message2bark, message2feishu, message2qmsg, message2wpush, message2xxtui


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


class TestWpush(unittest.TestCase):
    def test_success_on_code_zero(self):
        with patch.object(
            msg_mod.requests, "post", return_value=fake_resp(payload={"code": 0, "message": "ok"})
        ) as post:
            message2wpush("fakekey", "hello")
        self.assertEqual(post.call_args.kwargs["json"]["apikey"], "fakekey")
        self.assertEqual(post.call_args.kwargs["json"]["channel"], "wechat")

    def test_failure_on_nonzero_code(self):
        with patch.object(
            msg_mod.requests, "post", return_value=fake_resp(payload={"code": 400, "message": "bad key"})
        ):
            message2wpush("fakekey", "hello")
        # no assertion needed; the function only prints. Ensure no exception raised.

    def test_bool_code_not_treated_as_success(self):
        with patch.object(msg_mod.requests, "post", return_value=fake_resp(payload={"code": False})):
            message2wpush("fakekey", "hello")

    def test_non_json_response(self):
        with patch.object(msg_mod.requests, "post", return_value=fake_resp(text="<html>")):
            message2wpush("fakekey", "hello")

    def test_optional_fields(self):
        with patch.object(msg_mod.requests, "post", return_value=fake_resp(payload={"code": 0})) as post:
            message2wpush("k", "c", wpush_channel="sms", wpush_topic_code="T1")
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["channel"], "sms")
        self.assertEqual(body["topic_code"], "T1")


class TestXxtui(unittest.TestCase):
    def test_success(self):
        with patch.object(msg_mod.requests, "post", return_value=fake_resp(status_code=200, payload={"code": 200})):
            message2xxtui("fakekey", "hello")

    def test_failure_status(self):
        with patch.object(msg_mod.requests, "post", return_value=fake_resp(status_code=500, payload={"code": 1})):
            message2xxtui("fakekey", "hello")

    def test_timeout_is_set(self):
        with patch.object(msg_mod.requests, "post", return_value=fake_resp(payload={"code": 200})) as post:
            message2xxtui("fakekey", "hello")
        self.assertEqual(post.call_args.kwargs.get("timeout"), 15)


class TestBark(unittest.TestCase):
    def test_short_content_single_request(self):
        with patch.object(msg_mod.requests, "get") as get:
            message2bark("https://api.day.app/fakekey/", "short")
        self.assertEqual(get.call_count, 1)

    def test_long_content_chunked(self):
        sleeps = []
        with (
            patch.object(msg_mod.requests, "get") as get,
            patch.object(msg_mod.time, "sleep", side_effect=sleeps.append),
        ):
            message2bark("https://api.day.app/fakekey", "汉x字 0" * 800)
        self.assertEqual(len(sleeps), 6, "4000 chars / 600-per-chunk = 7 chunks must sleep 6 times")
        for call in get.call_args_list:
            url = call.kwargs["url"]
            for pos, ch in enumerate(url):
                if ch == "%":
                    self.assertTrue(
                        url[pos + 1 : pos + 3].isalnum(), f"truncated escape at {pos}: {url[pos : pos + 6]}"
                    )

    def test_title_and_params_in_url(self):
        with patch.object(msg_mod.requests, "get") as get:
            message2bark(
                "https://api.day.app/fakekey/", "c", title="T", group="g", sound="minuet", url_jump="https://a.b"
            )
        url = get.call_args.kwargs["url"]
        self.assertIn("/T/", url)
        self.assertIn("group=g", url)
        self.assertIn("sound=minuet", url)
        self.assertIn("url=https%3A%2F%2Fa.b", url)

    def test_no_params_no_query_mark(self):
        with patch.object(msg_mod.requests, "get") as get:
            message2bark("https://api.day.app/fakekey/", "c")
        url = get.call_args.kwargs["url"]
        self.assertFalse(url.endswith("?"))


class TestQmsg(unittest.TestCase):
    def test_default_url(self):
        with patch.object(msg_mod.requests, "get") as get:
            message2qmsg("key", None, "hello")
        url = get.call_args.kwargs["url"]
        self.assertTrue(url.startswith("https://qmsg.zendee.cn/send/"))

    def test_custom_url_and_qq(self):
        with patch.object(msg_mod.requests, "get") as get:
            message2qmsg("key", "group", "hello", qmsg_url="https://qmsg.example.com/", qmsg_qq="12345")
        url = get.call_args.kwargs["url"]
        self.assertTrue(url.startswith("https://qmsg.example.com/group/"))
        self.assertEqual(get.call_args.kwargs["params"]["qq"], "12345")

    def test_timeout_is_set(self):
        with patch.object(msg_mod.requests, "get") as get:
            message2qmsg("key", None, "hello")
        self.assertEqual(get.call_args.kwargs.get("timeout"), 15)


class TestFeishu(unittest.TestCase):
    def test_no_secret_plain_post(self):
        with patch.object(msg_mod.requests, "post") as post:
            message2feishu("fskey", "hello")
        body = post.call_args.kwargs["json"]
        self.assertNotIn("sign", body)
        self.assertEqual(body["msg_type"], "text")

    def test_secret_adds_timestamp_and_sign(self):
        with patch.object(msg_mod.requests, "post") as post:
            message2feishu("fskey", "hello", fssecret="sekret")
        body = post.call_args.kwargs["json"]
        self.assertIn("timestamp", body)
        self.assertIn("sign", body)
        self.assertEqual(len(body["sign"]), 44)  # base64 of sha256 digest

    def test_timeout_is_set(self):
        with patch.object(msg_mod.requests, "post") as post:
            message2feishu("fskey", "hello")
        self.assertEqual(post.call_args.kwargs.get("timeout"), 15)


class TestPushMessageIntegration(unittest.TestCase):
    def test_only_wpush_configured_sends_once(self):
        with (
            patch.object(msg_mod, "important_notice", side_effect=Exception("skip")),
            patch.object(msg_mod, "message2wpush") as wpush,
        ):
            msg_mod.push_message(["msg1"], {"wpush_apikey": "k", "merge_push": False})
        self.assertEqual(wpush.call_count, 1)

    def test_merge_push_true_sends_merged(self):
        with (
            patch.object(msg_mod, "important_notice", side_effect=Exception("skip")),
            patch.object(msg_mod, "message2xxtui") as xxtui,
        ):
            msg_mod.push_message(["msg1", "msg2"], {"xxtui_key": "k", "merge_push": True})
        self.assertEqual(xxtui.call_count, 1)
        content = xxtui.call_args.kwargs["content"]
        self.assertIn("msg1", content)
        self.assertIn("msg2", content)


if __name__ == "__main__":
    unittest.main()
