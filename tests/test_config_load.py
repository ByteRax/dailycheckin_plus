"""基线特征测试：config.json 加载行为。

锁定 dailycheckin/main.py 的 check_config()（main.py:21-63）真实行为：
- 正常加载：多账号 list 结构，服务键小写化输出，通知键小写化输出
- 文件缺失：checkin() 友好退出（打印提示，不抛未捕获异常）
- JSON 损坏：同理友好退出
- 模板占位（"xxxxxx" / "多账号"）账号被过滤；配置键大小写敏感（必须大写）

测试全部离线：只调用配置解析路径，不触发任何签到服务与网络请求。
注意 checkin() 内部 parse_arguments() 读取 sys.argv，测试中必须替换为干净 argv。
"""

import json
import sys

import pytest

from dailycheckin.configs import checkin_map, get_checkin_info, get_notice_info, notice_map
from dailycheckin.main import check_config, checkin

ALL_TASKS = list(checkin_map.keys())


def _write_config(tmp_path, data, filename="config.json"):
    config_path = tmp_path / filename
    config_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return config_path


@pytest.fixture
def clean_argv(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dailycheckin"])


VALID_MULTI_ACCOUNT_CONFIG = {
    "FNNASCLUB": [{"cookie": "account-one"}, {"cookie": "account-two"}],
    "BILIBILI": [{"cookie": "bilibili-one"}],
    "PUSHPLUS_TOKEN": "test-pushplus-token",
}


def test_load_multi_account_list(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path, VALID_MULTI_ACCOUNT_CONFIG)

    notice_info, check_info = check_config(ALL_TASKS)

    # 打印实际使用的配置文件路径
    out = capsys.readouterr().out
    assert "使用配置文件路径:" in out
    assert str(config_path) in out

    # 多账号 list 结构按配置原样加载，键小写化
    assert check_info["fnnasclub"] == [{"cookie": "account-one"}, {"cookie": "account-two"}]
    assert check_info["bilibili"] == [{"cookie": "bilibili-one"}]

    # 通知配置键小写化加载
    assert notice_info["pushplus_token"] == "test-pushplus-token"


def test_get_checkin_info_defaults_missing_service_to_empty_list():
    data = {"FNNASCLUB": [{"cookie": "only-one"}]}
    result = get_checkin_info(data=data)
    assert result["fnnasclub"] == [{"cookie": "only-one"}]
    assert result["bilibili"] == []
    assert set(result.keys()) == {key.lower() for key in checkin_map.keys()}


def test_get_notice_info_defaults_missing_notice_to_none():
    result = get_notice_info(data={})
    assert set(result.keys()) == {key.lower() for key in notice_map.keys()}
    assert all(value is None for value in result.values())


def test_missing_config_file_exits_friendly(tmp_path, monkeypatch, capsys, clean_argv):
    monkeypatch.chdir(tmp_path)

    # checkin() 不抛未捕获异常
    assert checkin() is None

    out = capsys.readouterr().out
    assert "未找到 config.json 配置文件" in out
    assert "请在下方任意目录中添加「config.json」文件" in out

    # check_config 对缺失文件返回 (False, False)
    assert check_config(ALL_TASKS) == (False, False)


def test_bad_json_exits_friendly(tmp_path, monkeypatch, capsys, clean_argv):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text("{not valid json", encoding="utf-8")

    assert checkin() is None

    out = capsys.readouterr().out
    assert "Json 格式错误，请检查 config.json 文件格式是否正确！" in out
    assert check_config(ALL_TASKS) == (False, False)


def test_template_placeholder_accounts_are_filtered(tmp_path, monkeypatch, capsys):
    # 模板占位账号（docker/config.template.json 遗留的 "xxxxxx" / "多账号"）被剔除
    monkeypatch.chdir(tmp_path)
    _write_config(
        tmp_path,
        {
            "FNNASCLUB": [{"cookie": "real-account"}],
            "BILIBILI": [{"cookie": "xxxxxx"}],
            "V2EX": [{"token": "多账号 token 使用 @ 分割"}],
        },
    )

    _, check_info = check_config(ALL_TASKS)

    assert check_info["fnnasclub"] == [{"cookie": "real-account"}]
    # 占位账号被剔除后为空的服务不会出现在结果中
    assert "bilibili" not in check_info
    assert "v2ex" not in check_info


def test_config_service_keys_are_case_sensitive(tmp_path, monkeypatch):
    # 配置键必须使用大写服务名；小写键不会被加载（当前真实行为）
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, {"v2ex": [{"token": "t"}]})

    _, check_info = check_config(ALL_TASKS)

    assert check_info == {}


def test_checkin_skips_execution_when_no_effective_account(tmp_path, monkeypatch, capsys, clean_argv):
    # 有效配置文件但所有账号均为占位符时，checkin() 直接结束，不执行任务、不联网
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, {"FNNASCLUB": [{"cookie": "xxxxxx"}]})

    assert checkin() is None

    out = capsys.readouterr().out
    assert "使用配置文件路径:" in out
    assert "本次执行签到任务如下" not in out
    assert "开始执行" not in out
