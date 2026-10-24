# bilibili 离线回归测试。
#
# Refs: Sitoi/dailycheckin#588 #586 #585 #515
# - #586/#588: dynamic/region 接口下线返回 {"code":-404,"data":null}，换 newlist 接口
# - #592 增量: data:null / archives 缺失 / aid_list 为空不崩溃
# - #585: is_login=False 时不再隐式返回 None（假成功），改抛明确异常
# - #515: 投币循环每次间隔 random 2-5 秒

import random
import time

import pytest

import dailycheckin.bilibili.main as bilibili_module
from dailycheckin.bilibili.main import BiliBili


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeCookieJar:
    def __iter__(self):
        return iter([])

    def set(self, name, value):
        pass

    def set_cookie(self, cookie):
        pass


class FakeSession:
    # 按 URL 子串路由返回预置 JSON，并记录全部请求及其参数。
    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.headers = {}
        self.cookies = FakeCookieJar()

    def get(self, url=None, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return FakeResponse(self._match(url))

    def post(self, url=None, data=None, json=None, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return FakeResponse(self._match(url))

    def _match(self, url):
        for substring, payload in self.routes:
            if substring in url:
                return payload
        raise AssertionError(f"unexpected url: {url}")

    def calls_to(self, substring, method="GET"):
        return [c for c in self.calls if c[0] == method and substring in c[1]]


NAV_OK = {
    "code": 0,
    "data": {
        "uname": "tester",
        "mid": 42,
        "isLogin": True,
        "money": 5,
        "vipType": 0,
        "level_info": {"current_exp": 100},
    },
}

REGION_DEAD = {"code": -404, "message": "啥都木有", "ttl": 1, "data": None}

REGION_OK = {
    "code": 0,
    "data": {
        "archives": [
            {"aid": 1001, "cid": 2001, "title": "video1", "owner": {"name": "up1"}},
            {"aid": 1002, "cid": 2002, "title": "video2", "owner": {"name": "up2"}},
        ]
    },
}

EXP_EMPTY = {"code": 0, "data": {"list": []}}

MANGA_OK = {"code": 0}
LIVE_SIGN_OK = {"code": 0, "data": {"text": "ok", "specialText": "sp", "hadSignDays": 3}}
VIP_MY_EMPTY = {"code": 0, "data": {"list": []}}
FOLLOWINGS_EMPTY = {"code": 0, "data": {"list": []}}
LIVE_STATUS_OK = {"code": 0, "data": {"silver": 1, "gold": 2, "coin": 3}}
COIN_ADD_OK = {"code": 0, "message": "0"}
REPORT_OK = {"code": 0}
SHARE_OK = {"code": 0}

BASE_ROUTES = [
    ("web-interface/nav", NAV_OK),
    ("dynamic/region", REGION_DEAD),  # 旧接口：无论谁请求都返回已下线响应
    ("web-interface/newlist", REGION_OK),
    ("member/web/exp/log", EXP_EMPTY),
    ("activity.v1.Activity/ClockIn", MANGA_OK),
    ("xlive/web-ucenter/v1/sign/DoSign", LIVE_SIGN_OK),
    ("vip/privilege/my", VIP_MY_EMPTY),
    ("relation/followings", FOLLOWINGS_EMPTY),
    ("pay/v1/Exchange/getStatus", LIVE_STATUS_OK),
    ("web-interface/coin/add", COIN_ADD_OK),
    ("v2/history/report", REPORT_OK),
    ("web-interface/share/add", SHARE_OK),
]


def _check_item(**overrides):
    item = {
        "cookie": "bili_jct=token123; SESSDATA=sess",
        "coin_num": 0,
        "coin_type": 0,
        "silver2coin": False,
    }
    item.update(overrides)
    return item


def _run_main(session, check_item):
    # 注入 FakeSession 后运行 BiliBili.main()。
    real_requests = bilibili_module.requests

    class _FakeRequests:
        utils = real_requests.utils

        @staticmethod
        def session():
            return session

    bilibili_module.requests = _FakeRequests
    try:
        return BiliBili(check_item=check_item).main()
    finally:
        bilibili_module.requests = real_requests


def test_get_region_uses_newlist_api_and_survives_null_data():
    # #586: 旧接口 data:null 不应抛 AttributeError，且应改用 newlist 接口（PR 588）。
    session = FakeSession([("dynamic/region", REGION_DEAD), ("web-interface/newlist", REGION_DEAD)])
    data_list = BiliBili.get_region(session=session)
    assert data_list == []
    assert len(session.calls_to("web-interface/newlist")) == 1
    assert session.calls_to("dynamic/region") == []


def test_get_region_newlist_ok_path():
    # PR 588: newlist 接口正常返回 archives（aid/cid/title/owner）。
    session = FakeSession([("web-interface/newlist", REGION_OK)])
    data_list = BiliBili.get_region(session=session)
    assert data_list == [
        {"aid": 1001, "cid": 2001, "title": "video1", "owner": "up1"},
        {"aid": 1002, "cid": 2002, "title": "video2", "owner": "up2"},
    ]


def test_get_region_request_has_timeout():
    session = FakeSession([("web-interface/newlist", REGION_OK)])
    BiliBili.get_region(session=session)
    (_method, _url, kwargs) = session.calls_to("web-interface/newlist")[0]
    assert kwargs.get("timeout") == 10


def test_main_raises_when_cookie_invalid():
    # #585: is_login=False 应抛明确异常，而不是隐式返回 None 打 ✅。
    session = FakeSession([("web-interface/nav", {"code": 0, "data": {"uname": "", "mid": 0, "isLogin": False}})])
    with pytest.raises(Exception, match="Bilibili Cookie 已失效"):
        _run_main(session, _check_item())


def test_main_degrades_when_region_dead(monkeypatch):
    # #586+#592: region 接口 data:null / aid_list 为空 → 不崩溃，输出跳过类降级文案。
    routes = [pair for pair in BASE_ROUTES if pair[0] != "web-interface/newlist"]
    routes.append(("web-interface/newlist", REGION_DEAD))
    session = FakeSession(routes)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    msg = _run_main(session, _check_item(coin_num=1, coin_type=0))
    assert "跳过投币" in msg
    assert "跳过观看" in msg
    assert "跳过分享" in msg


def test_main_followings_null_data_does_not_crash(monkeypatch):
    # #592: followings 返回 data:null 不应 AttributeError。
    routes = [pair for pair in BASE_ROUTES if pair[0] != "relation/followings"]
    routes.append(("relation/followings", {"code": 0, "data": None}))
    session = FakeSession(routes)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    msg = _run_main(session, _check_item(coin_num=0, coin_type=1))
    assert "帐号信息" in msg


def test_coin_loop_sleeps_random_2_to_5_seconds(monkeypatch):
    # #515: 连续投币之间应 sleep(random.uniform(2, 5))。
    session = FakeSession(BASE_ROUTES)
    sleeps = []
    uniform_args = []

    def _fake_uniform(a, b):
        uniform_args.append((a, b))
        return 3.0

    monkeypatch.setattr(time, "sleep", sleeps.append)
    monkeypatch.setattr(random, "uniform", _fake_uniform)
    msg = _run_main(session, _check_item(coin_num=2, coin_type=0))
    # 两枚硬币之间恰好间隔一次
    assert sleeps == [3.0]
    assert uniform_args == [(2, 5)]
    assert "今日成功投币2/2" in msg
