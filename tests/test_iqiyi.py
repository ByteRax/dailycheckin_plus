# iqiyi 离线回归测试。
#
# Refs: 安全审查 A09 H-3（2026-10-24）
# - vipgrowth/query.action 携 P00001 登录令牌，原为 http:// 明文；
#   https 版无凭据探测 200+证书校验通过（返回业务码 Q00304 用户未登录），改走 https

import time

import dailycheckin.iqiyi.main as iqiyi_module
from dailycheckin.iqiyi.main import IQIYI


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_user_information_uses_https(monkeypatch):
    recorded = []

    def fake_get(url=None, params=None, **kwargs):
        recorded.append((url, params))
        return FakeResponse(
            {
                "code": "A00000",
                "data": {
                    "level": 3,
                    "growthvalue": 100,
                    "distance": 50,
                    "deadline": "2099-01-01",
                    "todayGrowthValue": 5,
                },
            }
        )

    monkeypatch.setattr(iqiyi_module.requests, "get", fake_get)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    msg = IQIYI.user_information(p00001="token-x")
    assert recorded == [("https://serv.vip.iqiyi.com/vipgrowth/query.action", {"P00001": "token-x"})]
    assert msg[0] == {"name": "VIP 等级", "value": 3}


def test_user_information_error_path_uses_https(monkeypatch):
    recorded = []

    def fake_get(url=None, params=None, **kwargs):
        recorded.append(url)
        return FakeResponse({"code": "Q00304", "msg": "用户未登录"})

    monkeypatch.setattr(iqiyi_module.requests, "get", fake_get)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    msg = IQIYI.user_information(p00001="token-x")
    assert msg == [{"name": "账号信息", "value": "用户未登录"}]
    assert all(url.startswith("https://serv.vip.iqiyi.com/") for url in recorded)
