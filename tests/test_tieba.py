# tieba 离线回归测试。
#
# Refs: Sitoi/dailycheckin#509
# - 签到接口域名已由 http://c.tieba.baidu.com 变更为 https://tiebac.baidu.com（issue 内抓包证实）

import time

from dailycheckin.tieba.main import Tieba

COOKIE = "BDUSS=placeholder"


def test_sign_url_constant():
    tieba = Tieba(check_item={"cookie": COOKIE})
    assert tieba.SIGN_URL == "https://tiebac.baidu.com/c/c/forum/sign"


def _sign_forums_with(monkeypatch, response):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    tieba = Tieba(check_item={"cookie": COOKIE})
    recorded = []

    def fake_request(self, url, method="get", data=None, retry=3):
        recorded.append((method, url))
        return response

    monkeypatch.setattr(Tieba, "request", fake_request)
    stats = tieba.sign_forums([{"name": "测试吧", "id": "1"}], tbs="tbs-token")
    return stats, recorded


def test_sign_forums_success(monkeypatch):
    stats, recorded = _sign_forums_with(monkeypatch, {"error_code": "0", "user_info": {"user_sign_rank": "3"}})
    assert stats["success"] == 1
    assert stats["error"] == 0
    assert recorded == [("post", "https://tiebac.baidu.com/c/c/forum/sign")]


def test_sign_forums_already_signed(monkeypatch):
    stats, _recorded = _sign_forums_with(monkeypatch, {"error_code": "160002", "error_msg": "今日已签到"})
    assert stats["exist"] == 1
    assert stats["success"] == 0


def test_sign_forums_failure(monkeypatch):
    stats, _recorded = _sign_forums_with(monkeypatch, {"error_code": "1", "error_msg": "签到失败"})
    assert stats["error"] == 1
    assert stats["success"] == 0
