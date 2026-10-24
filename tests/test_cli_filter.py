"""基线特征测试：--include / --exclude 过滤逻辑。

过滤逻辑内联在 dailycheckin/main.py:checkin()（main.py:70-81）中，无法单独调用，
且带有效配置直接调用 checkin() 会执行真实签到任务（联网）。因此按计划采用替代策略：
1. parse_arguments() 可直接调用，做真正的单元测试；
2. include/exclude 的核心语义（未知服务名剔除 + 集合差）按 main.py:73-81 的原式
   复算出 task_list，再驱动可离线调用的 check_config(task_list)，验证
   「checkin_map 键名集合与配置键的交集」行为。不为测试修改产品代码。
"""

import json
import sys

import pytest

from dailycheckin.configs import checkin_map
from dailycheckin.main import check_config, parse_arguments

CONFIG_WITH_TWO_SERVICES = {
    "FNNASCLUB": [{"cookie": "fn-account"}],
    "BILIBILI": [{"cookie": "bili-account"}],
}


@pytest.fixture
def config_two_services(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(
        json.dumps(CONFIG_WITH_TWO_SERVICES, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)


def resolve_task_list(include, exclude):
    # 与 main.py:73-81 完全一致的过滤表达式（不引入额外语义）
    if not include:
        include = list(checkin_map.keys())
    else:
        include = [one for one in include if one in checkin_map.keys()]
    if not exclude:
        exclude = []
    else:
        exclude = [one for one in exclude if one in checkin_map.keys()]
    return list(set(include) - set(exclude))


def test_parse_arguments_include_and_exclude(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["dailycheckin", "--include", "FNNASCLUB", "BILIBILI", "--exclude", "BILIBILI"],
    )
    args = parse_arguments()
    assert args.include == ["FNNASCLUB", "BILIBILI"]
    assert args.exclude == ["BILIBILI"]


def test_parse_arguments_defaults_to_none(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dailycheckin"])
    args = parse_arguments()
    assert args.include is None
    assert args.exclude is None


def test_default_includes_all_services(config_two_services):
    task_list = resolve_task_list(include=None, exclude=None)
    assert set(task_list) == set(checkin_map.keys())

    _, check_info = check_config(task_list)
    assert set(check_info.keys()) == {"fnnasclub", "bilibili"}


def test_include_drops_unknown_service_names(config_two_services):
    task_list = resolve_task_list(include=["FNNASCLUB", "NOT_A_SERVICE"], exclude=None)
    assert "NOT_A_SERVICE" not in task_list

    _, check_info = check_config(task_list)
    assert set(check_info.keys()) == {"fnnasclub"}
    assert check_info["fnnasclub"] == [{"cookie": "fn-account"}]


def test_include_selects_only_requested_services(config_two_services):
    task_list = resolve_task_list(include=["BILIBILI"], exclude=None)

    _, check_info = check_config(task_list)
    assert set(check_info.keys()) == {"bilibili"}


def test_exclude_removes_service_from_default_all(config_two_services):
    task_list = resolve_task_list(include=None, exclude=["FNNASCLUB"])
    assert "FNNASCLUB" not in task_list

    _, check_info = check_config(task_list)
    assert set(check_info.keys()) == {"bilibili"}


def test_exclude_wins_over_include(config_two_services):
    # task_list = set(include) - set(exclude)：同时出现时 exclude 优先
    task_list = resolve_task_list(include=["FNNASCLUB", "BILIBILI"], exclude=["BILIBILI"])
    assert set(task_list) == {"FNNASCLUB"}

    _, check_info = check_config(task_list)
    assert set(check_info.keys()) == {"fnnasclub"}


def test_task_list_only_intersects_with_configured_keys(config_two_services):
    # include 的服务未在 config.json 配置时，不会凭空出现在 check_info 中
    task_list = resolve_task_list(include=["V2EX", "FNNASCLUB"], exclude=None)

    _, check_info = check_config(task_list)
    assert set(check_info.keys()) == {"fnnasclub"}
