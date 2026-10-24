# youdao 离线回归测试。
#
# Refs: 安全审查 A09 H-3（2026-10-24）
# - login/acc/pe/getsess 携 YNOTE_SESS/YNOTE_PERS Cookie，原为 http:// 明文；
#   https 版无凭据探测与 http 基线响应完全一致（500 ecode 2035），证书校验通过，改走 https

import json

import dailycheckin.youdao.main as youdao_module
from dailycheckin.youdao.main import YouDao

GETSESS_BODY = '{"reward": true, "rewardSpace": 1048576}'
CHECKIN_BODY = '{"space": 1048576}'
AD_BODY = '{"space": 0}'


class FakeCookies(dict):
    pass


class FakeResponse:
    def __init__(self, text, cookies=None):
        self.text = text
        self.cookies = cookies or FakeCookies()

    def json(self):
        return json.loads(self.text)


def _fake_requests(monkeypatch, recorded):
    class _FakeRequests:
        @staticmethod
        def get(url=None, cookies=None, **kwargs):
            recorded.append(("GET", url))
            return FakeResponse("{}", cookies=FakeCookies({"YNOTE_SESS": "s2"}))

        @staticmethod
        def post(url=None, cookies=None, **kwargs):
            recorded.append(("POST", url))
            if "daupromotion" in url:
                return FakeResponse(GETSESS_BODY)
            if "method=checkin" in url:
                return FakeResponse(CHECKIN_BODY)
            if "method=adRandomPrompt" in url:
                return FakeResponse(AD_BODY)
            raise AssertionError(f"unexpected url: {url}")

    real_requests = youdao_module.requests
    monkeypatch.setattr(youdao_module, "requests", _FakeRequests)
    return real_requests


def test_sign_refreshes_session_over_https(monkeypatch):
    recorded = []
    _fake_requests(monkeypatch, recorded)
    msg = YouDao.sign(cookies={"YNOTE_SESS": "s1", "YNOTE_PERS": "p1"})
    assert msg == "+2M"  # sync 1M + checkin 1M + ad 0M×3
    getsess_calls = [r for r in recorded if "getsess" in r[1]]
    assert getsess_calls == [("GET", "https://note.youdao.com/login/acc/pe/getsess?product=YNOTE")]
    # 其余端点本就是 https，不得出现任何 http:// 明文请求
    assert all(r[1].startswith("https://") for r in recorded)
