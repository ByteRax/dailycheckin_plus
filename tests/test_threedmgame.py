import unittest
from unittest.mock import Mock, patch

from dailycheckin.configs import checkin_map, get_checkin_info
from dailycheckin.threedmgame.main import ThreeDMGame


class ThreeDMGameTests(unittest.TestCase):
    def setUp(self):
        self.client = ThreeDMGame({"cookie": "test=secret"})
        self.client.session = Mock()

    @patch.dict("os.environ", {"bbs3dmck": "a=one@b=two"})
    def test_qinglong_env_fallback_and_explicit_config_precedence(self):
        result = get_checkin_info({})
        self.assertEqual(result["threedmgame"], [{"cookie": "a=one"}, {"cookie": "b=two"}])
        result = get_checkin_info({"THREEDMGAME": [{"cookie": "explicit"}]})
        self.assertEqual(result["threedmgame"], [{"cookie": "explicit"}])

    def response(self, text):
        response = Mock(text=text)
        response.raise_for_status = Mock()
        return response

    def test_registration_and_empty_cookie(self):
        self.assertIn("THREEDMGAME", checkin_map)
        with self.assertRaisesRegex(ValueError, "Cookie"):
            ThreeDMGame({}).main()

    @patch("dailycheckin.threedmgame.main.time.sleep")
    def test_apply_and_draw(self, sleep):
        self.client.session.get.side_effect = [
            self.response('<div class="ptm"><table><tr><td></td><td><h3><a>任务A</a></h3></td><td></td><td><a href="home.php?mod=task&amp;do=apply&amp;id=42">申请</a></td></tr></table></div>'),
            self.response("do=draw"), self.response("恭喜您，任务已成功完成"),
        ]
        self.client.apply_tasks()
        self.assertIn("奖励领取成功", self.client.messages[-1])
        self.assertIn("id=42", self.client.session.get.call_args.args[0])

    @patch("dailycheckin.threedmgame.main.time.sleep")
    def test_public_reply_then_draw(self, sleep):
        detail = '<table class="tfm"><tr><td class="bbda"><a href="thread-123-1-1.html">帖子</a>回复 1 次</td></tr></table>'
        thread = '<input name="formhash" value="abcdef"><script>fid = parseInt(\'5\'); tid = parseInt(\'123\');</script>'
        self.client.session.get.side_effect = [self.response(detail), self.response(thread), self.response("恭喜您，任务已成功完成")]
        self.client.session.post.return_value = self.response("回复发布成功")
        with patch("dailycheckin.threedmgame.main.requests.get", side_effect=ValueError("offline")):
            self.client.do_task("42", "回帖")
        self.assertEqual(self.client.session.post.call_count, 1)
        self.assertIn("tid=123", self.client.session.post.call_args.args[0])
        self.assertIn("奖励领取成功", self.client.messages[-1])

    @patch("dailycheckin.threedmgame.main.time.sleep")
    def test_reply_attempt_counts_and_partial_on_retry(self, sleep):
        detail = '<table class="tfm"><tr><td class="bbda"><a href="thread-123-1-1.html">帖子</a>回复 1 次</td></tr></table>'
        thread = """<input name="formhash" value="abcdef"><script>fid = parseInt('5'); tid = parseInt('123');</script>"""
        self.client.session.get.side_effect = [self.response(detail), self.response(thread), self.response("恭喜您，任务已成功完成")]
        with patch.object(self.client, "reply", side_effect=[False, True]):
            self.client.do_task("42", "回帖")
        self.assertEqual(self.client.outcome, "partial")
        self.assertIn("回帖成功 0 次，失败 1 次", self.client.messages[0])
        self.assertIn("回帖成功 1 次，失败 1 次", self.client.messages[1])

    @patch("dailycheckin.threedmgame.main.time.sleep")
    def test_reply_exception_retains_counts_and_propagates(self, sleep):
        detail = '<table class="tfm"><tr><td class="bbda"><a href="thread-123-1-1.html">帖子</a>回复 2 次</td></tr></table>'
        thread = """<input name="formhash" value="abcdef"><script>fid = parseInt('5'); tid = parseInt('123');</script>"""
        self.client.session.get.side_effect = [self.response(detail), self.response(thread)]
        with patch.object(self.client, "reply", side_effect=[True, ConnectionError("secret reply")]):
            with self.assertRaises(ConnectionError):
                self.client.do_task("42", "回帖")
        self.assertEqual(self.client.outcome, "partial")
        self.assertIn("回帖成功 1 次，失败 1 次", self.client.messages[-1])
        self.assertNotIn("secret reply", "\n".join(self.client.messages))

    @patch("dailycheckin.threedmgame.main.time.sleep")
    def test_apply_draw_failures_and_success_outcome(self, sleep):
        row = '<div class="ptm"><table><tr><td></td><td><h3><a>任务A</a></h3></td><td></td><td><a href="home.php?mod=task&amp;do=apply&amp;id=42">申请</a></td></tr></table></div>'
        self.client.session.get.side_effect = [self.response(row), self.response("申请失败"), self.response("领取失败")]
        self.assertEqual(self.client.outcome, "success")
        self.client.apply_tasks()
        self.assertEqual(self.client.outcome, "partial")
        self.client.outcome = "success"
        self.client.draw("42", "任务A")
        self.assertEqual(self.client.outcome, "partial")

    def test_invalid_cookie_stops_before_tasks(self):
        self.client.session.get.return_value = self.response("<html>请登录</html>")
        with self.assertRaisesRegex(ValueError, "Cookie"):
            self.client.main()
        self.assertEqual(self.client.session.get.call_count, 1)
        self.client.session.close.assert_called_once()

    @patch("dailycheckin.threedmgame.main.time.sleep")
    def test_unrecognized_or_excessive_reply_count_is_skipped(self, sleep):
        detail = '<table class="tfm"><tr><td class="bbda"><a href="thread-1-1-1.html">帖子</a>回复 6 次</td></tr></table>'
        self.client.session.get.return_value = self.response(detail)
        self.client.do_task("9", "过多回复")
        self.client.session.post.assert_not_called()
        self.assertIn("跳过", self.client.messages[-1])

    def test_network_failure_closes_session(self):
        self.client.session.get.side_effect = ConnectionError("offline")
        with self.assertRaises(ConnectionError):
            self.client.main()
        self.client.session.close.assert_called_once()

    def test_external_links_are_rejected(self):
        with self.assertRaises(ValueError):
            self.client.get("https://example.com/")
        self.client.session.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
