# 喜马拉雅离线回归测试。
#
# Refs: Sitoi/dailycheckin#452
# - 接口事实取自维护报告 A03 §2（参考实现 ClydeTime/Quantumult xmlySign.js 与
#   lzwme/ql-scripts ql_xmlySign.ts，仅取接口事实不抄代码）：
#   POST https://hybrid.ximalaya.com/web-activity/signIn/v2/signIn?v=new，
#   JSON body {"aid":87}，Cookie 鉴权，ret==0 为成功；msg 可能在顶层或 data.msg。
# - 响应中连续签到/奖励字段名无公开抓包证据，本文件 fixture 固定字段名
#   （continuousDays/awardName），模块按候选键防御式提取，缺失不报错。
#
# 全部 HTTP 请求经 responses mock。无真实凭据、无网络访问。

import json

import pytest
import responses

import dailycheckin.ximalaya.main as ximalaya_module
from dailycheckin.ximalaya.main import Ximalaya

SIGN_URL = "https://hybrid.ximalaya.com/web-activity/signIn/v2/signIn"
COOKIE = "1&_token=abc; device_id=demo"


@pytest.fixture
def rsps():
    with responses.RequestsMock() as mock:
        yield mock


def _check_in(cookie=COOKIE):
    return Ximalaya(check_item={"cookie": cookie}).main()


def test_success_with_continuous_days_and_award(rsps):
    """ret=0 且带连签/奖励字段: 输出签到成功 + 连续签到天数 + 奖励。"""
    rsps.add(
        responses.POST,
        SIGN_URL,
        json={"ret": 0, "msg": "成功", "data": {"continuousDays": 5, "awardName": "积分+5"}},
    )

    msg = _check_in()

    assert "签到成功" in msg
    assert "成功: 成功" in msg  # 顶层 msg 透出
    assert "连续签到: 5 天" in msg
    assert "签到奖励: 积分+5" in msg
    # 请求形态：查询串 v=new、body {"aid":87}、Cookie 头随请求发出
    request = rsps.calls[0].request
    assert "v=new" in request.url
    assert json.loads(request.body) == {"aid": 87}
    assert COOKIE in request.headers["Cookie"]


def test_success_without_optional_fields(rsps):
    """ret=0 但无连签/奖励字段: 字段缺失不报错, msg 回退到 data.msg。"""
    rsps.add(responses.POST, SIGN_URL, json={"ret": 0, "data": {"msg": "ok"}})

    msg = _check_in()

    assert "签到成功: ok" in msg
    assert "连续签到" not in msg
    assert "签到奖励" not in msg


def test_success_zero_days_still_reported(rsps):
    """连签天数为 0 也应输出(0 是有效值, 不是缺失)。"""
    rsps.add(responses.POST, SIGN_URL, json={"ret": 0, "data": {"continuousDays": 0}})

    msg = _check_in()

    assert "连续签到: 0 天" in msg


def test_business_failure_passthrough_msg(rsps):
    """ret!=0 带 msg: 失败文案含 ret 与 msg(无「已签到」文案证据, msg 原样透传)。"""
    rsps.add(responses.POST, SIGN_URL, json={"ret": 1001, "msg": "今日已签到"})

    msg = _check_in()

    assert "签到失败" in msg
    assert "1001" in msg
    assert "今日已签到" in msg


def test_business_failure_without_msg_falls_back(rsps):
    """ret!=0 且无 msg: 给出抓 cookie 的可行动回退文案。"""
    rsps.add(responses.POST, SIGN_URL, json={"ret": 31})

    msg = _check_in()

    assert "签到失败" in msg
    assert "31" in msg
    assert "Cookie" in msg


def test_network_error(rsps):
    """网络异常: 明确网络异常文案, 不抛出。"""
    rsps.add(responses.POST, SIGN_URL, body=responses.ConnectionError("boom"))

    msg = _check_in()

    assert "签到失败" in msg
    assert "网络异常" in msg


def test_cookie_expired_http_401(rsps):
    """HTTP 401: 明确判定 Cookie 已失效。"""
    rsps.add(responses.POST, SIGN_URL, status=401, json={})

    msg = _check_in()

    assert "Cookie 已失效" in msg
    assert "401" in msg


def test_cookie_expired_html_login_page(rsps):
    """200 但返回 HTML 登录页(非 JSON): 明确判定 Cookie 已失效。"""
    rsps.add(responses.POST, SIGN_URL, body="<html>请登录</html>", content_type="text/html")

    msg = _check_in()

    assert "Cookie 已失效" in msg


def test_malformed_json_body(rsps):
    """JSON 合法但非对象: 响应格式异常文案, 不抛 AttributeError。"""
    rsps.add(responses.POST, SIGN_URL, json=[])

    msg = _check_in()

    assert "签到失败" in msg
    assert "响应格式异常" in msg


def test_missing_cookie_sends_no_request(rsps):
    """未配置 cookie: 不发任何请求, 直接失败文案。"""
    msg = Ximalaya(check_item={}).main()

    assert "签到失败" in msg
    assert "未配置 Cookie" in msg
    assert len(rsps.calls) == 0


def test_request_shape_timeout_and_headers(monkeypatch):
    """请求形态锁定: timeout=10、aid=87、v=new、UA 与 Cookie 头。"""

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ret": 0}

    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(ximalaya_module.requests, "post", fake_post)

    _check_in(cookie="a=1")

    assert captured["url"] == ximalaya_module.Ximalaya._SIGN_URL
    assert captured["params"] == {"v": "new"}
    assert captured["json"] == {"aid": 87}
    assert captured["timeout"] == 10
    assert captured["headers"]["Cookie"] == "a=1"
    assert captured["headers"]["User-Agent"] == ximalaya_module.Ximalaya._UA
    assert "application/json" in captured["headers"]["Content-Type"]
