# imaotai 离线回归测试。
#
# Refs: Sitoi/dailycheckin#563 #568
# - shop/list/slim/v3 对象存储路径已被上游删除（404 + XML NoSuchKey，issue 内 curl 直证），
#   get_location_count 需抛明确异常「门店列表接口已失效（疑似上游升级 v4），等待适配」，
#   不编造 v4 接口、不加无限重试。

import pytest

import dailycheckin.imaotai.main as imaotai_module
from dailycheckin.imaotai.main import IMAOTAI

NOSUCHKEY_BODY = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<Error><Code>NoSuchKey</Code><Message>The specified key does not exist.</Message></Error>"
)


class FakeResponse:
    def __init__(self, status_code, text, payload=None):
        self.status_code = status_code
        self.text = text
        self.payload = payload if payload is not None else {}

    def json(self):
        return self.payload


def _imaotai_instance():
    # 跳过 __init__ 内的 itunes 版本查询（真实网络请求）
    obj = IMAOTAI.__new__(IMAOTAI)
    obj.headers = {"current_session_id": "1719200000000"}
    return obj


def _call(obj):
    return obj.get_location_count(
        province="贵州省",
        city="贵阳市",
        item_code="11318",
        p_c_map={"贵州省": {"贵阳市": ["1"]}},
        source_data={"1": {"lat": 29.0, "lng": 119.0}},
        lat="29.83826",
        lng="102.182324",
        reserve_rule=0,
    )


def test_get_location_count_404_raises_clear_error(monkeypatch):
    obj = _imaotai_instance()
    monkeypatch.setattr(imaotai_module.requests, "get", lambda url, **kwargs: FakeResponse(404, NOSUCHKEY_BODY))
    with pytest.raises(Exception, match="门店列表接口已失效（疑似上游升级 v4），等待适配"):
        _call(obj)


def test_get_location_count_200_nosuchkey_body_raises(monkeypatch):
    obj = _imaotai_instance()
    monkeypatch.setattr(imaotai_module.requests, "get", lambda url, **kwargs: FakeResponse(200, NOSUCHKEY_BODY))
    with pytest.raises(Exception, match="门店列表接口已失效"):
        _call(obj)


def test_get_location_count_normal_path(monkeypatch):
    obj = _imaotai_instance()
    shops = [{"shopId": "1", "items": [{"itemId": "11318", "inventory": 5}]}]
    monkeypatch.setattr(
        imaotai_module.requests,
        "get",
        lambda url, **kwargs: FakeResponse(200, '{"data": {}}', payload={"data": {"shops": shops}}),
    )
    assert _call(obj) == "1"
