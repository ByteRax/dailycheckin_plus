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
import email as email_lib
from email.header import decode_header, make_header

import pytest

from dailycheckin.utils import message


def parse_sent_mail(raw):
    msg = email_lib.message_from_string(raw)
    payload = msg.get_payload(decode=True).decode("utf-8")
    subject = str(make_header(decode_header(msg["Subject"])))
    return {"to": msg["To"], "subject": subject, "payload": payload}


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


# ---------------------------------------------------------------------------
# SMTP 邮件（Sitoi/dailycheckin#579，参考已关闭 #527 思路，标准库 smtplib 重写）
# ---------------------------------------------------------------------------


class FakeSMTPClient:
    instances = []
    starttls_calls = 0

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.logins = []
        self.sent = []
        self.closed = False
        FakeSMTPClient.instances.append(self)

    def login(self, user, password):
        self.logins.append((user, password))

    def starttls(self):
        FakeSMTPClient.starttls_calls += 1

    def sendmail(self, from_addr, to_addrs, msg):
        self.sent.append((from_addr, to_addrs, msg))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTPClient.instances = []
    FakeSMTPClient.starttls_calls = 0
    monkeypatch.setattr(message.smtplib, "SMTP_SSL", FakeSMTPClient)
    monkeypatch.setattr(message.smtplib, "SMTP", FakeSMTPClient)
    return FakeSMTPClient


def test_smtp_default_port_465_uses_ssl(fake_smtp, capsys):
    message.message2smtp("smtp.example.com", "user@example.com", "pass", "hello")
    (client,) = fake_smtp.instances
    assert (client.host, client.port) == ("smtp.example.com", 465)
    assert client.timeout == 10
    assert client.logins == [("user@example.com", "pass")]
    assert client.sent[0][0] == "user@example.com"
    assert client.sent[0][1] == ["user@example.com"]  # 未配 smtp_to 时默认发给发件人
    parsed = parse_sent_mail(client.sent[0][2])
    assert parsed["subject"] == "签到通知"
    assert parsed["payload"] == "hello"
    assert fake_smtp.starttls_calls == 0
    assert "SMTP 邮件推送成功" in capsys.readouterr().out


def test_smtp_port_587_uses_starttls(fake_smtp):
    message.message2smtp("smtp.example.com", "user@example.com", "pass", "hello", smtp_port="587")
    (client,) = fake_smtp.instances
    assert client.port == 587
    assert fake_smtp.starttls_calls == 1
    assert client.sent, "STARTTLS 路径也要完成发送"


def test_smtp_ssl_override_selects_connection_mode(fake_smtp):
    # smtp_ssl=true 在 587 端口也走 SMTP_SSL；smtp_ssl=false 在 465 端口走 SMTP+STARTTLS
    message.message2smtp("smtp.example.com", "u@e.com", "p", "a", smtp_port="587", smtp_ssl="true")
    message.message2smtp("smtp.example.com", "u@e.com", "p", "b", smtp_port="465", smtp_ssl="false")
    assert fake_smtp.instances[0].port == 587
    assert fake_smtp.instances[1].port == 465
    assert fake_smtp.starttls_calls == 1  # 只有 smtp_ssl=false 那次走 STARTTLS


def test_smtp_multiple_recipients(fake_smtp):
    message.message2smtp(
        "smtp.example.com", "user@example.com", "pass", "hello", smtp_to="a@x.com, b@x.com"
    )
    (client,) = fake_smtp.instances
    assert client.sent[0][1] == ["a@x.com", "b@x.com"]
    parsed = parse_sent_mail(client.sent[0][2])
    assert parsed["to"] == "a@x.com, b@x.com"  # To 头含全部收件人


def test_smtp_auth_failure_prints_failure_without_raising(fake_smtp, capsys):
    def bad_login(user, password):
        raise RuntimeError("(535, b'authentication failed')")

    original = FakeSMTPClient.login
    FakeSMTPClient.login = bad_login
    try:
        message.message2smtp("smtp.example.com", "user@example.com", "pass", "hello")
    finally:
        FakeSMTPClient.login = original
    out = capsys.readouterr().out
    assert "SMTP 邮件推送失败" in out
    assert "SMTP 邮件推送成功" not in out


def test_push_message_dispatches_smtp_with_merge_split(monkeypatch, fake_smtp):
    monkeypatch.setattr(message, "important_notice", lambda: None)
    # 仅配置 SMTP 时 merge_push 默认拆分（smtp_* 组合在默认集合中），两条内容各发一次
    message.push_message(
        ["a", "b"],
        {"smtp_server": "smtp.example.com", "smtp_user": "u@e.com", "smtp_password": "p", "smtp_to": "a@x.com"},
    )
    sent_bodies = [body for client in fake_smtp.instances for _, _, body in client.sent]
    assert len(sent_bodies) == 2
    payloads = sorted(parse_sent_mail(body)["payload"] for body in sent_bodies)
    assert payloads == ["a", "b"]


# ---------------------------------------------------------------------------
# PushDeer（Sitoi/dailycheckin#558；重实现自 PR #366，未复用其代码）
# ---------------------------------------------------------------------------


def test_pushdeer_payload_text_desp(fake_http, capsys):
    message.message2pushdeer("pd-pushkey-1", "签到结果内容")
    (call,) = fake_http.calls
    assert call["method"] == "POST"
    assert call["url"] == "https://api2.pushdeer.com/message/push"
    assert call["data"] == {"pushkey": "pd-pushkey-1", "text": "签到通知", "desp": "签到结果内容"}
    assert call["timeout"] == 10
    assert "PushDeer 推送成功" in capsys.readouterr().out


def test_pushdeer_body_code_nonzero_is_failure(fake_http, capsys):
    # PushDeer 错误以 body 内 code 返回（如 9201 pushkey 无效），不能只看 HTTP 状态码
    fake_http.response = FakeResponse(status_code=200, json_data={"code": 9201, "error": "pushkey 不合法"})
    message.message2pushdeer("bad-key", "hello")
    out = capsys.readouterr().out
    assert "PushDeer 推送失败" in out
    assert "PushDeer 推送成功" not in out


def test_pushdeer_non_json_body_reports_failure(fake_http, capsys):
    fake_http.response = FakeResponse(status_code=502, json_data=None, text="<html>Bad Gateway</html>")
    message.message2pushdeer("pd-pushkey-1", "hello")
    assert "PushDeer 推送失败" in capsys.readouterr().out


def test_push_message_dispatches_pushdeer_with_merge_split(monkeypatch):
    monkeypatch.setattr(message, "important_notice", lambda: None)
    sent = []
    monkeypatch.setattr(message, "message2pushdeer", lambda **kw: sent.append(kw))
    # 仅配置 pushdeer 时 merge_push 默认拆分（pushdeer_pushkey 在默认集合中），两条内容各推一次
    message.push_message(["a", "b"], {"pushdeer_pushkey": "k"})
    assert sent == [{"pushdeer_pushkey": "k", "content": "a"}, {"pushdeer_pushkey": "k", "content": "b"}]


# ---------------------------------------------------------------------------
# wxPusher（重实现自 PR #366，未复用其代码）
# ---------------------------------------------------------------------------


def test_wxpusher_payload_uids_from_comma_string(fake_http, capsys):
    message.message2wxpusher("AT_appToken", "uid_1,uid_2", "签到结果内容")
    (call,) = fake_http.calls
    assert call["method"] == "POST"
    assert call["url"] == "https://wxpusher.zjiecode.com/api/send/message"
    assert call["json"] == {
        "appToken": "AT_appToken",
        "content": "签到结果内容",
        "contentType": 1,
        "uids": ["uid_1", "uid_2"],
    }
    assert call["timeout"] == 10
    assert "wxPusher 推送成功" in capsys.readouterr().out


def test_wxpusher_accepts_uid_list_directly(fake_http):
    message.message2wxpusher("AT_appToken", ["uid_1", " uid_2 "], "hello")
    assert fake_http.calls[0]["json"]["uids"] == ["uid_1", "uid_2"]


def test_wxpusher_body_code_nonzero_is_failure(fake_http, capsys):
    fake_http.response = FakeResponse(status_code=200, json_data={"code": 1001, "msg": "appToken 不合法"})
    message.message2wxpusher("bad-token", "uid_1", "hello")
    out = capsys.readouterr().out
    assert "wxPusher 推送失败" in out
    assert "appToken 不合法" in out
    assert "wxPusher 推送成功" not in out


def test_wxpusher_non_json_body_reports_failure(fake_http, capsys):
    fake_http.response = FakeResponse(status_code=200, json_data=None, text="<html>error</html>")
    message.message2wxpusher("AT_appToken", "uid_1", "hello")
    assert "wxPusher 推送失败" in capsys.readouterr().out


def test_push_message_dispatches_wxpusher_with_merge_split(monkeypatch):
    monkeypatch.setattr(message, "important_notice", lambda: None)
    sent = []
    monkeypatch.setattr(message, "message2wxpusher", lambda **kw: sent.append(kw))
    # 仅配置 wxpusher 时 merge_push 默认拆分（wxpusher_apptoken 在默认集合中），两条内容各推一次
    message.push_message(["a", "b"], {"wxpusher_apptoken": "tk", "wxpusher_uids": "u1,u2"})
    assert sent == [
        {"wxpusher_apptoken": "tk", "wxpusher_uids": "u1,u2", "content": "a"},
        {"wxpusher_apptoken": "tk", "wxpusher_uids": "u1,u2", "content": "b"},
    ]
