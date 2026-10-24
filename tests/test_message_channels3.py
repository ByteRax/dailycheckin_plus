"""通知渠道第三批离线测试(全部 monkeypatch requests, 无网络).

覆盖:
- Server酱³(sctp 前缀 sendkey -> uid.push.ft07.com)与 Turbo 双格式路由(Sitoi/dailycheckin#517);
- Server 酱成败按响应 body code/errno 判定(失败打日志不抛异常);
- bark sound 参数与超长内容分批发送(Sitoi/dailycheckin#320 剩余部分 #387 #523,
  Original idea by LastNever from Sitoi/dailycheckin#320 (reimplemented)).
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


def test_merge_push_default_merged_when_only_sendkey(monkeypatch, fake_http):
    # Server酱默认保持上游行为：合并为 1 条/次（Turbo 免费额度 5 条/天，拆分会造成额度回归）；
    # 需要逐条推送的用户可显式配置 MERGE_PUSH: false
    monkeypatch.setattr(message, "important_notice", lambda: None)
    message.push_message(["a", "b"], {"sendkey": "SCT9876TURBOKEY"})
    urls = [call["url"] for call in fake_http.calls]
    assert len(urls) == 1
    assert urls[0].startswith("https://sctapi.ftqq.com/")


def test_merge_push_default_merged_when_only_sckey(monkeypatch, fake_http):
    monkeypatch.setattr(message, "important_notice", lambda: None)
    message.push_message(["a", "b"], {"sckey": "SCU123OLDKEY"})
    urls = [call["url"] for call in fake_http.calls]
    assert len(urls) == 1
    assert urls[0].startswith("https://sc.ftqq.com/")


# ---------------------------------------------------------------------------
# bark：sound 参数与超长内容分批（Sitoi/dailycheckin#320 剩余部分 #387 #523；
# Original idea by LastNever from Sitoi/dailycheckin#320 (reimplemented)）
# ---------------------------------------------------------------------------


def test_bark_sound_query_param(fake_http):
    message.message2bark(
        "https://api.day.app/KEY",
        "签到",
        bark_group="daily",
        bark_icon="https://example.com/i.png",
        bark_sound="minuet",
    )
    (call,) = fake_http.calls
    assert call["method"] == "GET"
    assert (
        call["url"] == "https://api.day.app/KEY/%E7%AD%BE%E5%88%B0"
        "?group=daily&icon=https%3A%2F%2Fexample.com%2Fi.png&sound=minuet"
    )
    assert call["timeout"] == 10


def test_bark_push_message_passes_sound(monkeypatch):
    monkeypatch.setattr(message, "important_notice", lambda: None)
    sent = []
    monkeypatch.setattr(message, "message2bark", lambda **kw: sent.append(kw))
    message.push_message(["a"], {"bark_url": "u", "bark_sound": "alarm"})
    assert sent == [{"bark_url": "u", "content": "a", "bark_group": None, "bark_icon": None, "bark_sound": "alarm"}]


def test_bark_short_content_single_request_no_sleep(fake_http, sleep_recorder):
    message.message2bark("https://api.day.app/KEY", "短消息", bark_sound="minuet")
    assert len(fake_http.calls) == 1
    assert sleep_recorder == []


def test_bark_long_content_split_by_lines(fake_http, sleep_recorder):
    lines = [f"第{i:03d}行 签到结果内容{i}" for i in range(1, 121)]
    content = "\n".join(lines)
    message.message2bark(
        "https://api.day.app/KEY",
        content,
        bark_group="daily",
        bark_icon="https://example.com/i.png",
        bark_sound="minuet",
    )
    assert len(fake_http.calls) > 1
    for call in fake_http.calls:
        assert len(call["url"]) <= 2000, f"URL 超长: {len(call['url'])}"
        # 每条分批都带相同的 group/icon/sound
        assert "group=daily" in call["url"]
        assert "icon=" in call["url"]
        assert "sound=minuet" in call["url"]
    # 分批之间间隔 1s（最后一条后不再 sleep）
    assert sleep_recorder == [1] * (len(fake_http.calls) - 1)
    # 内容不丢：首行与末行分别出现在第一条与最后一条 URL 中
    assert unquote_plus(fake_http.calls[0]["url"].rsplit("/", 1)[1].split("?")[0]).startswith("第001行")
    assert unquote_plus(fake_http.calls[-1]["url"].rsplit("/", 1)[1].split("?")[0]).split("\n")[-1] == lines[-1]


def test_bark_single_oversize_line_hard_split(fake_http, sleep_recorder):
    content = "长" * 4000  # 无换行：触发单行二分硬切
    message.message2bark("https://api.day.app/KEY", content)
    assert len(fake_http.calls) > 1
    for call in fake_http.calls:
        assert len(call["url"]) <= 2000
    assert sleep_recorder == [1] * (len(fake_http.calls) - 1)
    # 硬切不丢字符：解码后的各段拼接还原原文
    chunks = [unquote_plus(call["url"].rsplit("/", 1)[1].split("?")[0]) for call in fake_http.calls]
    assert "".join(chunks) == content


def test_bark_batch_partial_failure_visible_no_raise(monkeypatch, capsys, sleep_recorder):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        # 第 1 条失败（HTTP 400），第 2 条成功：失败可见、不抛异常、后续条继续发送
        status = 400 if len(calls) == 1 else 200
        return FakeResponse(status_code=status, json_data={"code": status})

    monkeypatch.setattr(message.requests, "get", fake_get)
    lines = [f"第{i:03d}行 签到结果内容{i}" for i in range(1, 121)]
    message.message2bark("https://api.day.app/KEY", "\n".join(lines), bark_sound="minuet")
    assert len(calls) > 1
    out = capsys.readouterr().out
    assert "推送失败" in out
    assert "推送成功" in out


def test_bark_single_request_http_error_is_failure(monkeypatch, capsys):
    monkeypatch.setattr(
        message.requests,
        "get",
        lambda url, **kwargs: FakeResponse(status_code=401, json_data={"code": 401}),
    )
    message.message2bark("https://api.day.app/KEY", "hello")
    out = capsys.readouterr().out
    assert "推送失败" in out
    assert "推送成功" not in out


def test_serverchan_and_bark_exception_logs_redact_urls(monkeypatch, capsys):
    # 网络异常串含完整 URL（sendkey 路径段/编码内容），日志必须打码（A09 round-2 M-1）

    def raise_with_url(*a, **kw):
        raise Exception("HTTPSConnectionPool(host='sctapi.ftqq.com'): url: /SCT123TSECRETKEY.send")

    monkeypatch.setattr(message.requests, "post", raise_with_url)
    message._serverchan_send("https://sctapi.ftqq.com/SCT123TSECRETKEY.send", {"title": "t"})
    out = capsys.readouterr().out
    assert "SCT123TSECRETKEY" not in out
    assert "<url-redacted>" in out
