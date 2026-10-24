# tieba 离线回归测试。
#
# Refs: Sitoi/dailycheckin#509
# - 签到接口域名已由 http://c.tieba.baidu.com 变更为 https://tiebac.baidu.com（issue 内抓包证实）
# Refs: 安全审查 A09 H-3（2026-10-24）
# - LIKE_URL 改 https：无凭据探测 https://c.tieba.baidu.com/c/f/forum/like 返回 200+证书校验通过，
#   POST 空表单响应与 http 基线逐字节一致，BDUSS 表单不再明文传输
# - TBS_URL 保持 http：https 版服务端 301 强制跳回 http://...?red_tag=...（多 UA 复测一致），
#   改 https 多一跳重定向且凭据最终仍明文，无安全收益，维持现状

import time

from dailycheckin.tieba.main import Tieba

COOKIE = "BDUSS=placeholder"


def test_sign_url_constant():
    tieba = Tieba(check_item={"cookie": COOKIE})
    assert tieba.SIGN_URL == "https://tiebac.baidu.com/c/c/forum/sign"


def test_like_url_uses_https():
    # BDUSS 经 LIKE_URL POST 表单发送，必须走 https
    tieba = Tieba(check_item={"cookie": COOKIE})
    assert tieba.LIKE_URL == "https://c.tieba.baidu.com/c/f/forum/like"


def test_tbs_url_intentionally_kept_http():
    # 服务端 https 版 301 强制降级回 http（red_tag），改 https 无安全收益；
    # 该断言防止未来无证据地切换，若百度修复降级策略可连同此测试一并更新
    tieba = Tieba(check_item={"cookie": COOKIE})
    assert tieba.TBS_URL == "http://tieba.baidu.com/dc/common/tbs"


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
