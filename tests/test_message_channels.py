"""通知渠道离线测试（全部 monkeypatch requests，无网络）。

覆盖：
- utils/message.py 全部推送请求带 timeout=10（横切回归）；
- push_message 内单渠道异常隔离（一坏不影响其他渠道与整体流程）。
"""

import pytest

from dailycheckin.utils import message


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON object could be decoded")
        return self._json_data


class RequestRecorder:
    def __init__(self):
        self.calls = []
        self.response = FakeResponse(json_data={"code": 0})

    def post(self, url, **kwargs):
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self.response

    def get(self, url, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self.response


@pytest.fixture
def fake_http(monkeypatch):
    recorder = RequestRecorder()
    monkeypatch.setattr(message.requests, "post", recorder.post)
    monkeypatch.setattr(message.requests, "get", recorder.get)
    return recorder


# ---------------------------------------------------------------------------
# 横切：所有推送请求必须带 timeout=10
# ---------------------------------------------------------------------------


def test_all_push_requests_have_timeout(fake_http):
    message.message2server("sckey", "hello")
    message.message2server_turbo("sendkey", "hello")
    message.message2coolpush("cpkey", "hello")
    message.message2qmsg("qkey", None, "hello")
    message.message2telegram(None, None, "bottoken", "userid", "hello")
    message.message2feishu("fskey", "hello")
    message.message2dingtalk("secret", "token", "hello")
    message.message2bark("https://api.day.app/KEY", "hello")
    message.message2qywxrobot("qywxkey", "hello")
    message.message2qywxapp("corpid", "1000001", "corpsecret", "touser", None, None, "hello")
    message.message2pushplus("pptoken", "hello")
    message.message2gotify("https://gotify.example.com", "gtoken", "5", "hello")
    message.message2ntfy("https://ntfy.example.com", "topic", "3", "hello")
    message.message2wpush("apikey1", "hello")
    message.message2xxtui("xxtuikey", "hello")
    # important_notice 在 push_message 推送路径上，同样不允许无限挂起
    fake_http.response = FakeResponse(json_data=[])
    message.important_notice()
    assert fake_http.calls, "没有记录到任何请求"
    for call in fake_http.calls:
        assert call["timeout"] == 10, f"{call['method']} {call['url']} 缺少 timeout=10"
    # 每个渠道函数都确实发出了请求
    assert len(fake_http.calls) >= 16


# ---------------------------------------------------------------------------
# 横切：单渠道异常隔离
# ---------------------------------------------------------------------------


def test_push_message_one_failing_channel_does_not_block_others(monkeypatch, capsys):
    monkeypatch.setattr(message, "important_notice", lambda: None)

    def broken_qmsg(**kwargs):
        raise RuntimeError("qmsg service down")

    sent = []

    def fake_bark(**kwargs):
        sent.append(kwargs["content"])

    monkeypatch.setattr(message, "message2qmsg", broken_qmsg)
    monkeypatch.setattr(message, "message2bark", fake_bark)

    # qmsg_key 在 merge_push 默认拆分集合中，两条内容各推一次
    message.push_message(["a", "b"], {"qmsg_key": "k", "bark_url": "https://api.day.app/KEY"})

    assert sent == ["a", "b"]
    out = capsys.readouterr().out
    assert "qmsg 推送失败" in out
    assert "qmsg service down" in out


# ---------------------------------------------------------------------------
# WPUSH（Sitoi/dailycheckin#590）
# ---------------------------------------------------------------------------


def test_wpush_success_payload_and_options(fake_http, capsys):
    message.message2wpush("apikey1", "hello", wpush_channel="mail", wpush_topic_code="t9")
    (call,) = fake_http.calls
    assert call["method"] == "POST"
    assert call["url"] == "https://api.wpush.cn/api/v1/send"
    assert call["json"] == {
        "apikey": "apikey1",
        "title": "签到通知",
        "content": "hello",
        "channel": "mail",
        "topic_code": "t9",
    }
    assert call["timeout"] == 10
    assert call["allow_redirects"] is False
    assert "WPUSH 推送成功" in capsys.readouterr().out


def test_wpush_default_channel_is_wechat_without_topic(fake_http):
    message.message2wpush("apikey1", "hello")
    payload = fake_http.calls[0]["json"]
    assert payload["channel"] == "wechat"
    assert "topic_code" not in payload


def test_wpush_http_200_with_body_code_401_is_failure(fake_http, capsys):
    # WPUSH 鉴权失败时返回 HTTP 200 + body code 401（A02 live 验证），
    # 成败只能按 body code 判定，不能按 HTTP 状态码判定。
    fake_http.response = FakeResponse(status_code=200, json_data={"code": 401, "message": "apikey 无效"})
    message.message2wpush("badkey", "hello")
    out = capsys.readouterr().out
    assert "WPUSH 推送失败" in out
    assert "apikey 无效" in out
    assert "WPUSH 推送成功" not in out


def test_wpush_non_json_body_reports_failure_without_raising(fake_http, capsys):
    fake_http.response = FakeResponse(status_code=200, json_data=None, text="<html>Gateway Error</html>")
    message.message2wpush("apikey1", "hello")
    assert "WPUSH 推送失败" in capsys.readouterr().out


def test_push_message_dispatches_wpush_with_merge_split(monkeypatch):
    monkeypatch.setattr(message, "important_notice", lambda: None)
    sent = []
    monkeypatch.setattr(message, "message2wpush", lambda **kw: sent.append(kw))
    # 仅配置 WPUSH 时 merge_push 默认拆分（wpush_apikey 在默认集合中），两条内容各推一次
    message.push_message(["a", "b"], {"wpush_apikey": "k", "wpush_channel": "mail", "wpush_topic_code": "t"})
    assert [s["content"] for s in sent] == ["a", "b"]
    assert sent[0]["wpush_apikey"] == "k"
    assert sent[0]["wpush_channel"] == "mail"
    assert sent[0]["wpush_topic_code"] == "t"


# ---------------------------------------------------------------------------
# xxtui（Sitoi/dailycheckin#564）
# ---------------------------------------------------------------------------


def test_xxtui_payload(fake_http):
    message.message2xxtui("xxtuikey", "hello")
    (call,) = fake_http.calls
    assert call["method"] == "POST"
    assert call["url"] == "https://www.xxtui.com/xxtui/xxtuikey"
    assert call["json"] == {"from": "DailyCheckIn 每日签到脚本", "title": "每日签到", "content": "hello"}
    assert call["timeout"] == 10


def test_push_message_dispatches_xxtui_with_merge_split(monkeypatch):
    monkeypatch.setattr(message, "important_notice", lambda: None)
    sent = []
    monkeypatch.setattr(message, "message2xxtui", lambda **kw: sent.append(kw))
    # 仅配置 xxtui 时 merge_push 默认拆分（原 PR 564 漏补的默认集合成员）
    message.push_message(["a", "b"], {"xxtui_key": "k"})
    assert sent == [{"xxtui_key": "k", "content": "a"}, {"xxtui_key": "k", "content": "b"}]
