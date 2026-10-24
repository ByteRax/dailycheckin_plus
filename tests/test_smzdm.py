# smzdm 离线回归测试。
#
# Refs: Sitoi/dailycheckin#479 #571 #523
# - #479/#571: all_reward 三态防护：正常 reward_add / data:null（已签到）/ 结构缺失（解析降级+error_code）
# - robot_token / sign 响应判空，不再抛 NoneType/KeyError 裸异常
# - #523b: 抽奖活动已下线（active_id 失效），移除 active() 调用

import pytest

import dailycheckin.smzdm.main as smzdm_module
from dailycheckin.smzdm.main import SMZDM

HEADERS = {"Cookie": "placeholder"}

ROBOT_TOKEN_OK = {"error_code": 0, "data": {"token": "tok123"}}
CHECKIN_OK = {"error_code": 0, "error_msg": "签到成功", "data": {}}
REWARD_OK = {
    "error_code": 0,
    "data": {"normal_reward": {"reward_add": {"content": "5积分"}, "sub_title": "连续签到3天"}},
}


class FakeResponse:
    def __init__(self, payload, text=""):
        self.payload = payload
        self.text = text

    def json(self):
        return self.payload


def _patch_requests(monkeypatch, routes):
    # routes 按顺序子串匹配，先具体后宽泛；返回请求记录列表。
    calls = []

    def fake_post(url=None, data=None, headers=None, **kwargs):
        calls.append(("POST", url))
        for substring, payload in routes:
            if substring in url:
                return FakeResponse(payload)
        raise AssertionError(f"unexpected url: {url}")

    def fake_get(url=None, headers=None, **kwargs):
        calls.append(("GET", url))
        for substring, payload in routes:
            if substring in url:
                return FakeResponse(payload)
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(smzdm_module.requests, "post", fake_post)
    monkeypatch.setattr(smzdm_module.requests, "get", fake_get)
    return calls


def test_all_reward_normal_path(monkeypatch):
    _patch_requests(monkeypatch, [("/checkin/all_reward", REWARD_OK)])
    sm = SMZDM(check_item={"cookie": "ph"})
    msgs = sm.all_reward(HEADERS, data={})
    assert msgs == [
        {"name": "签到奖励", "value": "5积分"},
        {"name": "连续签到", "value": "连续签到3天"},
    ]


def test_all_reward_data_null_degrades(monkeypatch):
    # #571: data:null → 输出「今日已签到或无奖励信息」，不抛 NoneType is not subscriptable。
    _patch_requests(monkeypatch, [("/checkin/all_reward", {"error_code": 0, "data": None})])
    sm = SMZDM(check_item={"cookie": "ph"})
    msgs = sm.all_reward(HEADERS, data={})
    assert msgs == [{"name": "签到奖励", "value": "今日已签到或无奖励信息"}]


def test_all_reward_missing_reward_add_degrades(monkeypatch):
    # #479: normal_reward 缺 reward_add → 解析降级 + 原始 error_code，不抛 KeyError。
    _patch_requests(
        monkeypatch,
        [("/checkin/all_reward", {"error_code": 11, "data": {"normal_reward": {"sub_title": "x"}}})],
    )
    sm = SMZDM(check_item={"cookie": "ph"})
    msgs = sm.all_reward(HEADERS, data={})
    assert len(msgs) == 1
    assert "解析" in msgs[0]["value"]
    assert "11" in msgs[0]["value"]


def test_all_reward_normal_reward_none_degrades(monkeypatch):
    _patch_requests(monkeypatch, [("/checkin/all_reward", {"error_code": 0, "data": {"normal_reward": None}})])
    sm = SMZDM(check_item={"cookie": "ph"})
    msgs = sm.all_reward(HEADERS, data={})
    assert len(msgs) == 1
    assert "解析" in msgs[0]["value"]


def test_robot_token_null_data_raises_clear_error(monkeypatch):
    # robot_token 响应 data:null → 明确异常，而非 TypeError。
    _patch_requests(monkeypatch, [("robot/token", {"error_code": 9, "error_msg": "已开启验证码", "data": None})])
    sm = SMZDM(check_item={"cookie": "ph"})
    with pytest.raises(Exception, match="robot_token"):
        sm.robot_token(HEADERS)


def test_sign_missing_error_msg_degrades(monkeypatch):
    # sign 响应缺 error_msg → 降级文案，而非 KeyError。
    _patch_requests(monkeypatch, [("user-api.smzdm.com/checkin", {"error_code": 0, "data": {}})])
    sm = SMZDM(check_item={"cookie": "ph"})
    error_msg, _data = sm.sign(HEADERS, token="tok")
    assert "签到响应异常" in error_msg


def test_main_no_longer_calls_dead_lottery(monkeypatch):
    # #523b: 抽奖 active_id 已失效，main() 不应再请求 zhiyou.smzdm.com 抽奖接口。
    calls = _patch_requests(
        monkeypatch,
        [
            ("/checkin/all_reward", REWARD_OK),
            ("user-api.smzdm.com/checkin", CHECKIN_OK),
            ("robot/token", ROBOT_TOKEN_OK),
        ],
    )
    sm = SMZDM(check_item={"cookie": "ph"})
    msg = sm.main()
    urls = [u for (_method, u) in calls]
    assert not any("lottery" in u or "zhiyou.smzdm.com" in u for u in urls)
    assert "签到成功" in msg
    assert "签到奖励" in msg
