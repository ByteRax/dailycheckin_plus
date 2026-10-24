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


class TestDatetime:
    def test_checkin_no_utcnow_deprecation(self, monkeypatch, capsys):
        _patch_env(monkeypatch, [])
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            checkin()
        assert "当前时间" in capsys.readouterr().out
