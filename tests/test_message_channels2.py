"""通知渠道离线测试第二轮(全部 monkeypatch, 无网络).

新增 6 渠道(T-A06b):
- webhook 通用 Webhook(Sitoi/dailycheckin#578, 覆盖 #547 MeoW / #403 Synology Chat);
- pushme(Sitoi/dailycheckin#435);
- QLAPI 青龙桥(Sitoi/dailycheckin#573);
- SMTP 邮件(Sitoi/dailycheckin#579, 参考已关闭 #527 思路, 标准库重写);
- pushdeer(Sitoi/dailycheckin#558, 重实现自 PR #366, 未复用其代码);
- wxpusher(重实现自 PR #366, 未复用其代码).
"""

import builtins

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
# 通用 Webhook（Sitoi/dailycheckin#578，覆盖 #547 MeoW / #403 Synology Chat）
# ---------------------------------------------------------------------------


def test_webhook_post_default_template_renders_title_content(fake_http, capsys):
    message.message2webhook("https://hook.example.com/abc", "签到成功")
    (call,) = fake_http.calls
    assert call["method"] == "POST"
    assert call["url"] == "https://hook.example.com/abc"
    assert call["json"] == {"title": "签到通知", "content": "签到成功"}
    assert call["timeout"] == 10
    assert "Webhook 推送成功" in capsys.readouterr().out


def test_webhook_custom_template_renders_placeholders(fake_http):
    body = '{"text": "{title} - {content}", "extra": "static"}'
    message.message2webhook("https://hook.example.com/abc", "hello", webhook_body=body)
    assert fake_http.calls[0]["json"] == {"text": "签到通知 - hello", "extra": "static"}


def test_webhook_get_sends_title_content_as_params(fake_http, capsys):
    message.message2webhook("https://hook.example.com/abc", "hello", webhook_method="GET")
    (call,) = fake_http.calls
    assert call["method"] == "GET"
    assert call["url"] == "https://hook.example.com/abc"
    assert call["params"] == {"title": "签到通知", "content": "hello"}
    assert call["timeout"] == 10
    assert "Webhook 推送成功" in capsys.readouterr().out


def test_webhook_content_with_quotes_renders_valid_json(fake_http):
    # content 内含引号/换行时, 直接字符串替换会产出非法 JSON, 必须做 JSON 转义
    message.message2webhook("https://hook.example.com/abc", '他说 "hi"\n第二行')
    body = fake_http.calls[0]["json"]
    assert body == {"title": "签到通知", "content": '他说 "hi"\n第二行'}


def test_webhook_invalid_template_reports_failure_without_request(fake_http, capsys):
    message.message2webhook("https://hook.example.com/abc", "hello", webhook_body="{not valid json")
    out = capsys.readouterr().out
    assert "Webhook 推送失败" in out
    assert "模板" in out
    assert fake_http.calls == []


def test_webhook_non_2xx_reports_failure(fake_http, capsys):
    fake_http.response = FakeResponse(status_code=500, text="boom")
    message.message2webhook("https://hook.example.com/abc", "hello")
    out = capsys.readouterr().out
    assert "Webhook 推送失败" in out
    assert "500" in out
    assert "Webhook 推送成功" not in out


def test_push_message_dispatches_webhook_with_merge_split(monkeypatch):
    monkeypatch.setattr(message, "important_notice", lambda: None)
    sent = []
    monkeypatch.setattr(message, "message2webhook", lambda **kw: sent.append(kw))
    # 仅配置 webhook 时 merge_push 默认拆分（webhook_url 在默认集合中），两条内容各推一次
    message.push_message(
        ["a", "b"],
        {"webhook_url": "https://hook.example.com/abc", "webhook_method": "GET", "webhook_body": '{"t":"{title}"}'},
    )
    assert [s["content"] for s in sent] == ["a", "b"]
    assert sent[0]["webhook_url"] == "https://hook.example.com/abc"
    assert sent[0]["webhook_method"] == "GET"
    assert sent[0]["webhook_body"] == '{"t":"{title}"}'


# ---------------------------------------------------------------------------
# pushme（Sitoi/dailycheckin#435）
# ---------------------------------------------------------------------------


def test_pushme_get_with_url_encoded_params(fake_http, capsys):
    message.message2pushme("pushme-key-123", "签到 成功&下一行")
    (call,) = fake_http.calls
    assert call["method"] == "GET"
    assert call["url"] == "https://push.i-i.me/pushme-key-123"
    # title/content 必须经 requests params 机制 URL 编码，不得手工拼进 URL
    assert call["params"] == {"title": "签到通知", "content": "签到 成功&下一行"}
    assert "?" not in call["url"]
    assert call["timeout"] == 10
    assert "PushMe 推送成功" in capsys.readouterr().out


def test_pushme_non_2xx_reports_failure(fake_http, capsys):
    fake_http.response = FakeResponse(status_code=403, text="Forbidden")
    message.message2pushme("bad-key", "hello")
    out = capsys.readouterr().out
    assert "PushMe 推送失败" in out
    assert "403" in out
    assert "PushMe 推送成功" not in out


def test_push_message_dispatches_pushme_with_merge_split(monkeypatch):
    monkeypatch.setattr(message, "important_notice", lambda: None)
    sent = []
    monkeypatch.setattr(message, "message2pushme", lambda **kw: sent.append(kw))
    # 仅配置 pushme 时 merge_push 默认拆分（pushme_key 在默认集合中），两条内容各推一次
    message.push_message(["a", "b"], {"pushme_key": "k"})
    assert sent == [{"pushme_key": "k", "content": "a"}, {"pushme_key": "k", "content": "b"}]


# ---------------------------------------------------------------------------
# QLAPI 青龙桥（Sitoi/dailycheckin#573）
# ---------------------------------------------------------------------------


class FakeQLAPI:
    def __init__(self):
        self.notifications = []

    def systemNotify(self, payload):
        self.notifications.append(payload)


@pytest.fixture
def no_qlapi(monkeypatch):
    monkeypatch.delattr(builtins, "QLAPI", raising=False)


def test_qlapi_calls_system_notify_when_present(no_qlapi, monkeypatch, capsys):
    fake = FakeQLAPI()
    monkeypatch.setattr(builtins, "QLAPI", fake, raising=False)
    message.message2qlapi("签到内容")
    assert fake.notifications == [{"title": "签到通知", "content": "签到内容"}]
    out = capsys.readouterr().out
    assert "QLAPI 推送成功" in out
    assert "跳过" not in out


def test_qlapi_skips_without_qlapi_environment(no_qlapi, capsys):
    # 非青龙环境不得抛 NameError/AttributeError，「跳过」不算错误
    message.message2qlapi("签到内容")
    out = capsys.readouterr().out
    assert "未检测到青龙 QLAPI 环境，跳过" in out
    assert "失败" not in out


def test_push_message_dispatches_qlapi_with_merge_split(monkeypatch, no_qlapi):
    monkeypatch.setattr(message, "important_notice", lambda: None)
    fake = FakeQLAPI()
    monkeypatch.setattr(builtins, "QLAPI", fake, raising=False)
    # 仅配置 qlapi 时 merge_push 默认拆分（qlapi 在默认集合中），两条内容各推一次
    message.push_message(["a", "b"], {"qlapi": "true"})
    assert fake.notifications == [
        {"title": "签到通知", "content": "a"},
        {"title": "签到通知", "content": "b"},
    ]
