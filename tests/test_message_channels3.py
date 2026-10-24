"""通知渠道第三批离线测试(全部 monkeypatch requests, 无网络).

覆盖:
- Server酱³(sctp 前缀 sendkey -> uid.push.ft07.com)与 Turbo 双格式路由(Sitoi/dailycheckin#517);
- Server 酱成败按响应 body code/errno 判定(失败打日志不抛异常).
"""

from urllib.parse import unquote_plus

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
    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    def _next(self):
        if self.responses:
            return self.responses.pop(0)
        return FakeResponse(json_data={"code": 0})

    def post(self, url, **kwargs):
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self._next()

    def get(self, url, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self._next()


@pytest.fixture
def fake_http(monkeypatch):
    recorder = RequestRecorder()
    monkeypatch.setattr(message.requests, "post", recorder.post)
    monkeypatch.setattr(message.requests, "get", recorder.get)
    return recorder


@pytest.fixture
def sleep_recorder(monkeypatch):
    delays = []
    monkeypatch.setattr(message.time, "sleep", delays.append)
    return delays


# ---------------------------------------------------------------------------
# Server酱³ / Server酱 Turbo 双格式（Sitoi/dailycheckin#517）
# 官方文档：https://sc3.ft07.com/doc 、https://doc2.ft07.com/zh/serverchan3/server/api
# ---------------------------------------------------------------------------


def test_serverchan3_sendkey_uses_uid_push_endpoint(fake_http, capsys):
    message.message2server_turbo("sctp12345tABCdef678", "第一行\n第二行")
    (call,) = fake_http.calls
    assert call["method"] == "POST"
    assert call["url"] == "https://12345.push.ft07.com/send/sctp12345tABCdef678.send"
    assert call["data"]["title"] == "每日签到"
    assert call["data"]["desp"] == "第一行\n\n第二行"
    # tags 为 SC³ 专用参数（官方 API 文档），等价替换旧实现的 ?tags= 查询串
    assert call["data"]["tags"] == "DailyCheckin"
    assert call["timeout"] == 10
    out = capsys.readouterr().out
    assert "Server 酱³ 推送开始" in out
    assert "推送成功" in out


def test_serverchan_turbo_sendkey_uses_sctapi(fake_http):
    message.message2server_turbo("SCT9876TURBOKEY", "hello")
    (call,) = fake_http.calls
    assert call["url"] == "https://sctapi.ftqq.com/SCT9876TURBOKEY.send"
    assert call["data"]["title"] == "每日签到"
    assert "tags" not in call["data"]
    assert call["timeout"] == 10


def test_serverchan_failure_code_logged_not_raised(fake_http, capsys):
    fake_http.responses = [FakeResponse(json_data={"code": 40001, "message": "bad sendkey"})]
    message.message2server_turbo("SCT9876TURBOKEY", "hello")
    out = capsys.readouterr().out
    assert "推送失败" in out
    assert "bad sendkey" in out
    assert "推送成功" not in out


def test_serverchan_errno_shape_success_and_failure(monkeypatch, capsys):
    # 旧版 sc.ftqq.com 返回 errno/errmsg 形态；errno==0 同样判成功
    recorder = RequestRecorder(responses=[FakeResponse(json_data={"errno": 0, "errmsg": ""})])
    monkeypatch.setattr(message.requests, "post", recorder.post)
    message.message2server("SCU123OLDKEY", "hello")
    assert "推送成功" in capsys.readouterr().out

    recorder = RequestRecorder(responses=[FakeResponse(json_data={"errno": 1020, "errmsg": "blocked"})])
    monkeypatch.setattr(message.requests, "post", recorder.post)
    message.message2server("SCU123OLDKEY", "hello")
    out = capsys.readouterr().out
    assert "推送失败" in out
    assert "blocked" in out
    assert "推送成功" not in out


def test_serverchan_non_json_response_is_failure(fake_http, capsys):
    fake_http.responses = [FakeResponse(json_data=None)]
    message.message2server_turbo("SCT9876TURBOKEY", "hello")
    out = capsys.readouterr().out
    assert "推送失败" in out
    assert "推送成功" not in out


def test_sckey_with_sctp_key_routed_to_serverchan3(fake_http):
    # SC³ sendkey 误填进 SCKEY 也应走 ft07 端点，而不是打给已废弃的 sc.ftqq.com
    message.message2server("sctp777tXYZkey", "hello")
    (call,) = fake_http.calls
    assert call["url"] == "https://777.push.ft07.com/send/sctp777tXYZkey.send"
    assert call["data"]["tags"] == "DailyCheckin"


def test_sckey_with_sct_prefix_routed_to_sctapi(fake_http):
    # Turbo sendkey（SCT 前缀）误填进 SCKEY：走 sctapi.ftqq.com
    message.message2server("SCT555TURBOKEY", "hello")
    (call,) = fake_http.calls
    assert call["url"] == "https://sctapi.ftqq.com/SCT555TURBOKEY.send"
    assert call["data"]["title"] == "每日签到"


def test_sckey_legacy_scu_key_keeps_old_endpoint(fake_http):
    message.message2server("SCU123OLDKEY", "hello")
    (call,) = fake_http.calls
    assert call["url"] == "https://sc.ftqq.com/SCU123OLDKEY.send"
    # 旧端点参数为 text/desp（与旧实现一致）
    assert call["data"]["text"] == "每日签到"
    assert call["data"]["desp"] == "hello"


def test_merge_push_default_split_when_only_sendkey(monkeypatch, fake_http):
    monkeypatch.setattr(message, "important_notice", lambda: None)
    message.push_message(["a", "b"], {"sendkey": "SCT9876TURBOKEY"})
    urls = [call["url"] for call in fake_http.calls]
    assert len(urls) == 2
    assert all(url.startswith("https://sctapi.ftqq.com/") for url in urls)


def test_merge_push_default_split_when_only_sckey(monkeypatch, fake_http):
    monkeypatch.setattr(message, "important_notice", lambda: None)
    message.push_message(["a", "b"], {"sckey": "SCU123OLDKEY"})
    urls = [call["url"] for call in fake_http.calls]
    assert len(urls) == 2
    assert all(url.startswith("https://sc.ftqq.com/") for url in urls)
