# aolaxing 离线回归测试。
#
# Refs: 安全审查 A09 H-3（2026-10-24）
# - service.100bt.com 三个接口原为 http://，Cookie 头（登录态）明文传输；
#   https 版无凭据探测均 200+证书校验通过，响应与 http 基线一致（服务端已下线 code 503，两端同样），
#   传输层无差异，改走 https

import dailycheckin.aolaxing.main as aolaxing_module
from dailycheckin.aolaxing.main import AoLaXing

USER_OK = {"jsonResult": {"data": {"credit": 10, "creditHistory": 100, "phoneNum": "13800000000", "signInTotal": 5}}}

TASK_LIST = {
    "jsonResult": {
        "data": [
            {"name": "看视频", "status_desc": "已完成", "taskID": "1"},
            {"name": "逛商城", "status_desc": "未完成", "taskID": "2"},
        ]
    }
}

DO_TASK = {"jsonResult": {"message": "OK"}}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def _fake_requests(monkeypatch, recorded):
    def fake_get(url, headers=None, **kwargs):
        recorded.append(url)
        if "user_info" in url:
            return FakeResponse(USER_OK)
        if "daily_task_list" in url:
            return FakeResponse(TASK_LIST)
        if "do_task" in url:
            return FakeResponse(DO_TASK)
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(aolaxing_module.requests, "get", fake_get)


def test_all_endpoints_use_https(monkeypatch):
    recorded = []
    _fake_requests(monkeypatch, recorded)
    monkeypatch.setattr(aolaxing_module.time, "sleep", lambda s: None)

    aolaxing = AoLaXing(check_item={"cookie": "session=x"})
    msg = aolaxing.main()

    assert recorded == [
        "https://service.100bt.com/creditmall/activity/daily_task_list.jsonp?gameId=2&_=1643437206026",
        "https://service.100bt.com/creditmall/activity/do_task.jsonp?taskId=2&gameId=2&_=1643440166690",
        "https://service.100bt.com/creditmall/activity/daily_task_list.jsonp?gameId=2&_=1643437206026",
        "https://service.100bt.com/creditmall/my/user_info.jsonp",
    ]
    assert all(url.startswith("https://") for url in recorded)
    assert "13800000000" in msg
