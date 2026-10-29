import unittest
from unittest.mock import Mock, call, patch

import requests

from dailycheckin.configs import checkin_map, get_checkin_info
from dailycheckin.pojie52.main import Pojie52


class Pojie52Tests(unittest.TestCase):
    def setUp(self):
        network = patch("socket.socket.connect", side_effect=AssertionError("禁止真实网络"))
        network.start()
        self.addCleanup(network.stop)
        session_patch = patch("dailycheckin.pojie52.main.requests.Session")
        self.session_class = session_patch.start()
        self.addCleanup(session_patch.stop)
        self.session = self.session_class.return_value.__enter__.return_value
        self.session.headers = {}
        self.client = Pojie52({"cookie": "test=secret"})

    @staticmethod
    def response(text):
        return Mock(text=text)

    def test_successful_sign_in(self):
        self.session.get.side_effect = [
            self.response('<input name="formhash" value="abc123">'),
            self.response('<em>吾爱币:</em> 42 <em>积分：</em> 100'),
        ]
        self.session.post.return_value = self.response("签到成功")
        self.assertEqual(self.client.main(), "签到成功，吾爱币 42，积分 100")
        self.assertEqual(self.client.outcome, "success")
        self.assertEqual(self.session.headers["Cookie"], "test=secret")
        self.assertEqual(self.session.headers["Referer"], self.client.base)
        self.assertEqual(self.session.get.call_args_list, [
            call(self.client.sign_page, timeout=15),
            call(self.client.credit_page, timeout=15),
        ])
        self.session.post.assert_called_once_with(
            self.client.sign_post,
            data={"formhash": "abc123", "qdxq": "kx", "qdmode": "1", "todaysay": "每日签到", "fastreply": "0"},
            timeout=15,
        )

    def test_already_signed_does_not_post(self):
        for text in self.client.already_signed:
            with self.subTest(text=text):
                self.session.reset_mock()
                self.session.get.side_effect = [self.response(text), self.response('<em>积分:</em> 8')]
                self.assertEqual(self.client.main(), "今日已签到，积分 8")
                self.session.post.assert_not_called()

    def test_invalid_page_does_not_post(self):
        self.session.get.return_value = self.response("请先登录")
        with self.assertRaisesRegex(RuntimeError, "formhash"):
            self.client.main()
        self.session.post.assert_not_called()
        self.session.get.assert_called_once_with(self.client.sign_page, timeout=15)

    def test_network_failure_propagates(self):
        self.session.get.side_effect = requests.ConnectionError("offline")
        with self.assertRaises(requests.ConnectionError):
            self.client.main()
        self.session.post.assert_not_called()
        self.session_class.return_value.__exit__.assert_called_once()

    def test_credit_failure_preserves_sign_in_result(self):
        self.session.get.side_effect = [
            self.response('<input name="formhash" value="abc123">'),
            requests.Timeout("offline"),
        ]
        self.session.post.return_value = self.response("签到成功")
        self.assertEqual(self.client.main(), "签到成功，积分查询失败")
        self.assertEqual(self.client.outcome, "partial")
        self.session.post.assert_called_once()

    def test_registration_and_empty_cookie(self):
        self.assertEqual(checkin_map["POJIE52"], ("吾爱破解", Pojie52))
        with self.assertRaisesRegex(ValueError, "Cookie"):
            Pojie52({}).main()
        self.session_class.assert_not_called()

    def test_environment_multiple_accounts_and_config_precedence(self):
        expected = [{"cookie": "a=one"}, {"cookie": "b=two"}]
        for value in (" a=one\nb=two ", "a=one\r\nb=two", "a=one&b=two", "a=one#b=two"):
            with self.subTest(value=value), patch.dict("os.environ", {"POJIE52_COOKIE": value}, clear=True):
                for data in ({}, {"POJIE52": []}, None):
                    self.assertEqual(get_checkin_info(data)["pojie52"], expected)
                configured = [{"cookie": "configured"}]
                self.assertEqual(get_checkin_info({"POJIE52": configured})["pojie52"], configured)


if __name__ == "__main__":
    unittest.main()
