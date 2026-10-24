"""checkin() 调度行为的测试(不联网、无真实凭据)。"""

import sys
import warnings

import dailycheckin.main
from dailycheckin.main import checkin


def _patch_env(monkeypatch, argv, check_info=({}, {})):
    """准备最小执行环境: 假注册表 + 假配置, 捕获 check_config 收到的任务列表。"""
    captured = {}
    monkeypatch.setattr(sys, "argv", ["dailycheckin", *argv])
    monkeypatch.setattr(dailycheckin.main, "checkin_map", {"FAKE": ("假服务", None)})

    def fake_check_config(task_list):
        captured["task_list"] = task_list
        return check_info

    monkeypatch.setattr(dailycheckin.main, "check_config", fake_check_config)
    return captured


class TestIncludeExclude:
    def test_include_case_insensitive(self, monkeypatch, capsys):
        captured = _patch_env(monkeypatch, ["--include", "fake"])
        checkin()
        assert captured["task_list"] == ["FAKE"]
        assert "未找到" not in capsys.readouterr().out

    def test_exclude_case_insensitive(self, monkeypatch, capsys):
        captured = _patch_env(monkeypatch, ["--include", "FAKE", "--exclude", "fake"])
        checkin()
        out = capsys.readouterr().out
        assert "过滤后没有可执行的签到任务" in out
        assert "task_list" not in captured

    def test_include_unknown_warns_with_available(self, monkeypatch, capsys):
        captured = _patch_env(monkeypatch, ["--include", "nosuch"])
        checkin()
        out = capsys.readouterr().out
        assert "警告" in out and "nosuch" in out and "未找到" in out
        assert "可用服务" in out and "FAKE" in out
        assert "过滤后没有可执行的签到任务" in out
        assert "task_list" not in captured

    def test_exclude_unknown_warns_but_keeps_valid(self, monkeypatch, capsys):
        captured = _patch_env(monkeypatch, ["--include", "FAKE", "--exclude", "nosuch"])
        checkin()
        out = capsys.readouterr().out
        assert "警告" in out and "nosuch" in out
        assert captured["task_list"] == ["FAKE"]

    def test_empty_check_info_prints_message(self, monkeypatch, capsys):
        _patch_env(monkeypatch, ["--include", "fake"], check_info=({}, {}))
        checkin()
        assert "没有可执行的签到任务" in capsys.readouterr().out


class TestDatetime:
    def test_checkin_no_utcnow_deprecation(self, monkeypatch, capsys):
        _patch_env(monkeypatch, [])
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            checkin()
        assert "当前时间" in capsys.readouterr().out
