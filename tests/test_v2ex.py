# v2ex 离线回归测试。
#
# Refs: Sitoi/dailycheckin#525
# - 首页未匹配到 once 签到链接时应抛明确异常（由上层记 ❌），不再静默返回造成假成功

import pytest

import dailycheckin.v2ex.main as v2ex_module
from dailycheckin.v2ex.main import V2ex

MISSION_PAGE_NO_BUTTON = """
<html><body>
<div class="cell">每日登录奖励已经领取过了</div>
</body></html>
"""

MISSION_PAGE_WITH_BUTTON = """
<html><body>
<input type="button" class="super normal button" value="领取 50 铜币" onclick="location.href = '/mission/daily/once?once=6642079';" />
</body></html>
"""

BALANCE_PAGE = """
<html><body>
<td class="d" style="text-align: right;">12.34</td>
<td class="d"><span class="gray">每日登录奖励</span></td>
<a href="/member/tom" class="top">tom</a>
</body></html>
"""

MISSION_PAGE_DAYS = """
<html><body><div class="cell">连续登录 5 天</div></body></html>
"""


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeCookieJar:
    def __iter__(self):
        return iter([])

    def set(self, name, value):
        pass

    def set_cookie(self, cookie):
        pass


class SequentialFakeSession:
    # 按顺序消费的 (URL 子串, 响应体) 队列：同一 URL 的多次请求可返回不同页面。
    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.headers = {}
        self.proxies = {}
        self.cookies = FakeCookieJar()

    def get(self, url=None, **kwargs):
        for i, (substring, body) in enumerate(self.sequence):
            if substring in url:
                self.sequence.pop(i)
                return FakeResponse(body)
        raise AssertionError(f"unexpected url: {url}")


def test_sign_raises_when_once_link_missing():
    session = SequentialFakeSession([("/mission/daily", MISSION_PAGE_NO_BUTTON)])
    with pytest.raises(Exception, match="未找到签到入口"):
        V2ex.sign(session=session)


def test_main_raises_when_once_link_missing():
    session = SequentialFakeSession([("/mission/daily", MISSION_PAGE_NO_BUTTON)])
    real_requests = v2ex_module.requests

    class _FakeRequests:
        utils = real_requests.utils

        @staticmethod
        def session():
            return session

    v2ex_module.requests = _FakeRequests
    try:
        checkin = V2ex(check_item={"cookie": "A=1; B=2"})
        with pytest.raises(Exception, match="未找到签到入口（可能已签到或 Cookie 失效），请检查"):
            checkin.main()
    finally:
        v2ex_module.requests = real_requests


def test_sign_normal_path_still_works():
    session = SequentialFakeSession(
        [
            ("/mission/daily", MISSION_PAGE_WITH_BUTTON),
            ("/once?", ""),
            ("/balance", BALANCE_PAGE),
            ("/mission/daily", MISSION_PAGE_DAYS),
        ]
    )
    msg = V2ex.sign(session=session)
    names = {one["name"]: one["value"] for one in msg}
    assert names["帐号信息"] == "tom"
    assert names["帐号余额"] == "12.34"
    assert names["签到天数"] == "连续登录 5 天"


def test_sign_requests_keep_tls_verification():
    # Refs: 安全审查 A09 H-2（2026-10-24）
    # www.v2ex.com 证书链校验通过（无凭据探测 302/200），全部请求移除 verify=False，
    # A2 会话 Cookie 不再接受中间人证书
    class RecordingSession(SequentialFakeSession):
        def __init__(self, sequence):
            super().__init__(sequence)
            self.get_kwargs = []

        def get(self, url=None, **kwargs):
            self.get_kwargs.append(kwargs)
            return super().get(url=url, **kwargs)

    session = RecordingSession(
        [
            ("/mission/daily", MISSION_PAGE_WITH_BUTTON),
            ("/once?", ""),
            ("/balance", BALANCE_PAGE),
            ("/mission/daily", MISSION_PAGE_DAYS),
        ]
    )
    V2ex.sign(session=session)
    assert session.get_kwargs, "应发出至少一个请求"
    for kwargs in session.get_kwargs:
        assert kwargs.get("verify", True) is not False, "不得再传 verify=False"


def test_module_does_not_disable_warnings(monkeypatch):
    # Refs: 安全审查 A09 H-2（2026-10-24）
    # 模块导入不得调用 urllib3.disable_warnings()（进程级静默 InsecureRequestWarning）
    import importlib

    import urllib3

    calls = []
    monkeypatch.setattr(urllib3, "disable_warnings", lambda *a, **k: calls.append(a))
    importlib.reload(v2ex_module)
    try:
        assert calls == [], "模块导入不应调用 urllib3.disable_warnings()"
    finally:
        monkeypatch.undo()
        importlib.reload(v2ex_module)
