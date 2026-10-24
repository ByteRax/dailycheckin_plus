"""--accounts 参数(1-based 账号区间选择)的单元测试。

对应 Sitoi/dailycheckin#544 的重实现: 区间解析为纯函数 _parse_accounts_spec,
按服务切片为 _select_accounts。
"""

import sys

import pytest

import dailycheckin.main
from dailycheckin.main import _parse_accounts_spec, _select_accounts


class TestParseAccountsSpec:
    def test_single_value(self):
        assert _parse_accounts_spec("1") == [1]

    def test_single_range(self):
        assert _parse_accounts_spec("2-4") == [2, 3, 4]

    def test_single_value_range(self):
        assert _parse_accounts_spec("2-2") == [2]

    def test_mixed(self):
        assert _parse_accounts_spec("1,3-5") == [1, 3, 4, 5]

    def test_mixed_multiple_ranges(self):
        assert _parse_accounts_spec("1,3-4,7") == [1, 3, 4, 7]

    def test_dedupe_and_sort(self):
        assert _parse_accounts_spec("5,3-5,1") == [1, 3, 4, 5]

    def test_whitespace_tolerant(self):
        assert _parse_accounts_spec(" 1, 3-5 ") == [1, 3, 4, 5]

    @pytest.mark.parametrize(
        "spec",
        ["", "  ", "0", "1,0", "-1", "a", "1-a", "a-2", "5-3", "1-", "-", "1-3-5", "1,,2"],
    )
    def test_invalid_spec_raises(self, spec):
        with pytest.raises(ValueError):
            _parse_accounts_spec(spec)


class TestParseArgumentsAccounts:
    def test_valid_spec(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["dailycheckin", "--accounts", "1,3-5"])
        args = dailycheckin.main.parse_arguments()
        assert args.accounts == [1, 3, 4, 5]

    @pytest.mark.parametrize("spec", ["0", "a", "5-3"])
    def test_invalid_spec_exits_2(self, monkeypatch, capsys, spec):
        monkeypatch.setattr(sys, "argv", ["dailycheckin", "--accounts", spec])
        with pytest.raises(SystemExit) as excinfo:
            dailycheckin.main.parse_arguments()
        assert excinfo.value.code == 2
        assert "--accounts" in capsys.readouterr().err


class TestSelectAccounts:
    @pytest.fixture(autouse=True)
    def _fake_map(self, monkeypatch):
        monkeypatch.setattr(dailycheckin.main, "checkin_map", {"FAKE": ("假服务", None)})

    def test_slice_keeps_true_indices(self):
        accounts = [{"i": 1}, {"i": 2}, {"i": 3}]
        result = _select_accounts({"fake": accounts}, [1, 3])
        assert result == {"fake": [(0, {"i": 1}), (2, {"i": 3})]}

    def test_out_of_range_warns_and_truncates(self, capsys):
        accounts = [{"i": 1}, {"i": 2}, {"i": 3}]
        result = _select_accounts({"fake": accounts}, [1, 5, 7])
        assert result == {"fake": [(0, {"i": 1})]}
        out = capsys.readouterr().out
        assert "超出范围" in out
        assert "5" in out and "7" in out
        assert "假服务" in out

    def test_empty_after_slice_skips_service(self, capsys):
        accounts = [{"i": 1}, {"i": 2}, {"i": 3}]
        result = _select_accounts({"fake": accounts}, [5])
        assert result == {}
        out = capsys.readouterr().out
        assert "跳过该服务" in out
