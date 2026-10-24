# acfun 离线回归测试。
#
# Refs: 安全审查 A09 H-2（2026-10-24）
# - id.app.acfun.cn / api-ipv6.acfunchina.com 证书链校验通过（无凭据探测：200 业务错误 / 401 token error），
#   登录（账密 POST body）与分享（acPasstoken）接口移除 verify=False，不再接受中间人证书
# - 移除模块级 urllib3.disable_warnings()

import importlib

import urllib3

import dailycheckin.acfun.main as acfun_module
from dailycheckin.acfun.main import AcFun


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def post(self, url=None, data=None, headers=None, **kwargs):
        self.calls.append(("POST", url, kwargs))
        for substring, payload in self.routes:
            if substring in url:
                return FakeResponse(payload)
        raise AssertionError(f"unexpected url: {url}")

    def get(self, url=None, headers=None, cookies=None, **kwargs):
        self.calls.append(("GET", url, kwargs))
        for substring, payload in self.routes:
            if substring in url:
                return FakeResponse(payload)
        raise AssertionError(f"unexpected url: {url}")


def test_get_cookies_keeps_tls_verification():
    session = FakeSession([("id.app.acfun.cn/rest/app/login/signin", {"acPassToken": "t", "auth_key": 1})])
    cookies = AcFun.get_cookies(session, phone="13800000000", password="pw")
    assert cookies == {"acPasstoken": "t", "auth_key": "1"}
    (method, url, kwargs) = session.calls[0]
    assert method == "POST"
    assert url == "https://id.app.acfun.cn/rest/app/login/signin"
    assert kwargs.get("verify", True) is not False, "登录接口不得传 verify=False"


def test_share_keeps_tls_verification():
    acfun = AcFun(check_item={"phone": "13800000000", "password": "pw"})
    session = FakeSession([("reportTaskAction", {"result": 0})])
    msg = acfun.share(session=session, cookies={"acPasstoken": "t"})
    assert msg == {"name": "分享任务", "value": "分享成功"}
    (method, url, kwargs) = session.calls[0]
    assert method == "GET"
    assert url.startswith("https://api-ipv6.acfunchina.com/rest/app/task/reportTaskAction")
    assert kwargs.get("verify", True) is not False, "分享接口不得传 verify=False"


def test_module_does_not_disable_warnings(monkeypatch):
    calls = []
    monkeypatch.setattr(urllib3, "disable_warnings", lambda *a, **k: calls.append(a))
    importlib.reload(acfun_module)
    try:
        assert calls == [], "模块导入不应调用 urllib3.disable_warnings()"
    finally:
        monkeypatch.undo()
        importlib.reload(acfun_module)
