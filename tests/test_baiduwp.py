"""百度网盘 baiduwp 离线回归测试。

对应维护报告 A03 §3.3 (上游 issues #534/#577) 与 PR 591 A 部分 (cookie 回写) 的采纳加固。
全部 HTTP 请求经 responses mock, 无真实凭据、无网络访问; 配置文件用 tmp_path 隔离。
"""

import json
import os

import pytest
import responses

import dailycheckin.baiduwp.main as baiduwp_module
from dailycheckin.baiduwp.main import BaiduWP

SIGNIN_URL = "https://pan.baidu.com/rest/2.0/membership/level?app_id=250528&web=5&method=signin"
QUESTION_URL = "https://pan.baidu.com/act/v2/membergrowv2/getdailyquestion?app_id=250528&web=5"
ANSWER_URL = "https://pan.baidu.com/act/v2/membergrowv2/answerquestion?app_id=250528&web=5&ask_id=123&answer=2"
USERINFO_URL = "https://pan.baidu.com/rest/2.0/membership/user?app_id=250528&web=5&method=query"

COOKIE_0 = "BAIDUID=OLD1:FG=1; STOKEN=oldtoken1"
COOKIE_1 = "BAIDUID=OLD2:FG=1; STOKEN=oldtoken2"


def _write_config(tmp_path):
    config = {
        "MERGE_PUSH": "",
        "BAIDUWP": [
            {"cookie": COOKIE_0},
            {"cookie": COOKIE_1},
        ],
        "ENSHAN": [{"cookie": "keepme=1"}],
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    return path


def _mock_all_ok(mock, set_cookie=None):
    headers = {"Set-Cookie": set_cookie} if set_cookie else {}
    mock.add(responses.GET, SIGNIN_URL, body='{"errno":0,"points":5,}', headers=headers)
    mock.add(responses.GET, QUESTION_URL, body='{"errno":0,"ask_id":123,"answer":2,"question":"q"}')
    mock.add(responses.GET, ANSWER_URL, body='{"errno":0,"score":3,"show_msg":"回答正确"}')
    mock.add(responses.GET, USERINFO_URL, body='{"errno":0,"current_value":1234,"current_level":3}')


def _load_accounts(config_path):
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)["BAIDUWP"]


@pytest.fixture
def rsps():
    with responses.RequestsMock() as mock:
        yield mock


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(baiduwp_module.time, "sleep", lambda seconds: None)


class TestCookieWriteBack:
    def test_success_writes_back_only_target_account_cookie(self, tmp_path, monkeypatch, rsps, no_sleep):
        """签到成功且服务器下发新 cookie 时, 仅按索引回写当前账号的 cookie 字段。"""
        config_path = _write_config(tmp_path)
        monkeypatch.chdir(tmp_path)
        _mock_all_ok(rsps, set_cookie="STOKEN=newtoken2; Path=/; Domain=.baidu.com")

        account = _load_accounts(config_path)[1]
        msg = BaiduWP(check_item=account).main()

        assert "签到获得5" in msg
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["BAIDUWP"][0]["cookie"] == COOKIE_0
        assert data["BAIDUWP"][1]["cookie"] == "BAIDUID=OLD2:FG=1; STOKEN=newtoken2"
        assert data["ENSHAN"] == [{"cookie": "keepme=1"}]
        assert data["MERGE_PUSH"] == ""
        assert not (tmp_path / "config.json.tmp").exists()

    def test_no_new_cookie_no_write(self, tmp_path, monkeypatch, rsps, no_sleep):
        """无新 cookie (服务器未下发 Set-Cookie) 时不得改写配置文件。"""
        config_path = _write_config(tmp_path)
        monkeypatch.chdir(tmp_path)
        _mock_all_ok(rsps)

        before = config_path.read_text(encoding="utf-8")
        before_mtime = config_path.stat().st_mtime_ns
        msg = BaiduWP(check_item=_load_accounts(config_path)[0]).main()

        assert "签到获得5" in msg
        assert config_path.read_text(encoding="utf-8") == before
        assert config_path.stat().st_mtime_ns == before_mtime

    def test_signin_failure_never_writes_back(self, tmp_path, monkeypatch, rsps, no_sleep):
        """签到未明确成功时 (HTTP 502), 即使拿到新 cookie 也不回写。"""
        config_path = _write_config(tmp_path)
        monkeypatch.chdir(tmp_path)
        rsps.add(
            responses.GET,
            SIGNIN_URL,
            status=502,
            body="bad gateway",
            headers={"Set-Cookie": "STOKEN=newtoken0; Path=/; Domain=.baidu.com"},
        )
        rsps.add(responses.GET, QUESTION_URL, body="{}")
        rsps.add(responses.GET, USERINFO_URL, body="{}")

        before = config_path.read_text(encoding="utf-8")
        msg = BaiduWP(check_item=_load_accounts(config_path)[0]).main()

        assert "签到请求失败" in msg and "502" in msg
        assert config_path.read_text(encoding="utf-8") == before

    def test_replace_failure_keeps_original_file_and_warns(self, tmp_path, monkeypatch, rsps, no_sleep, capsys):
        """os.replace 抛错时: 原配置文件必须完好, 打印警告, 不影响签到结果上报。"""
        config_path = _write_config(tmp_path)
        monkeypatch.chdir(tmp_path)
        _mock_all_ok(rsps, set_cookie="STOKEN=newtoken2; Path=/; Domain=.baidu.com")

        def _boom(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", _boom)
        before = config_path.read_text(encoding="utf-8")
        msg = BaiduWP(check_item=_load_accounts(config_path)[1]).main()

        assert "签到获得5" in msg
        assert config_path.read_text(encoding="utf-8") == before
        assert not (tmp_path / "config.json.tmp").exists()
        assert "写回" in capsys.readouterr().out

    def test_account_not_found_on_disk_skips_write(self, tmp_path, monkeypatch, rsps, no_sleep, capsys):
        """config.json 在运行期间被改动 (快照匹配不到账号) 时跳过写回并警告, 不误写他人。"""
        config_path = _write_config(tmp_path)
        monkeypatch.chdir(tmp_path)
        _mock_all_ok(rsps, set_cookie="STOKEN=newtoken1; Path=/; Domain=.baidu.com")

        account = _load_accounts(config_path)[0]
        data = json.loads(config_path.read_text(encoding="utf-8"))
        data["BAIDUWP"][0]["cookie"] = "BAIDUID=CHANGED:FG=1"
        config_path.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
        changed = config_path.read_text(encoding="utf-8")

        BaiduWP(check_item=account).main()

        assert config_path.read_text(encoding="utf-8") == changed
        assert "写回" in capsys.readouterr().out

    def test_missing_config_file_no_crash(self, tmp_path, monkeypatch, rsps, no_sleep):
        """找不到 config.json (未配置) 时静默跳过回写, 签到结果正常返回。"""
        monkeypatch.chdir(tmp_path)
        _mock_all_ok(rsps, set_cookie="STOKEN=newtoken1; Path=/; Domain=.baidu.com")

        msg = BaiduWP(check_item={"cookie": COOKIE_0}).main()

        assert "签到获得5" in msg
        assert not (tmp_path / "config.json.tmp").exists()


class TestCredentialHygiene:
    def test_failure_message_does_not_leak_cookie(self, tmp_path, monkeypatch, rsps, no_sleep):
        """#534 关联修复: 非 200 失败分支的错误信息不得包含 Cookie 明文。"""
        monkeypatch.chdir(tmp_path)
        rsps.add(responses.GET, SIGNIN_URL, status=502, body="bad gateway")
        rsps.add(responses.GET, QUESTION_URL, body="{}")
        rsps.add(responses.GET, USERINFO_URL, body="{}")

        msg = BaiduWP(check_item={"cookie": "BAIDUID=LEAKMARK:FG=1; STOKEN=secrettoken"}).main()

        assert "签到请求失败" in msg
        assert "LEAKMARK" not in msg
        assert "secrettoken" not in msg

    def test_cookie_sent_via_session_jar(self, tmp_path, monkeypatch, rsps, no_sleep):
        """cookie 经 session cookie jar 附带 (591 方案), Set-Cookie 更新可在后续请求生效。"""
        monkeypatch.chdir(tmp_path)
        _mock_all_ok(rsps, set_cookie="STOKEN=newtoken1; Path=/; Domain=.baidu.com")

        BaiduWP(check_item={"cookie": COOKIE_0}).main()

        signin_cookie = rsps.calls[0].request.headers["Cookie"]
        assert "BAIDUID=OLD1:FG=1" in signin_cookie
        assert "STOKEN=oldtoken1" in signin_cookie
        # 后续请求 (答题/查询) 应带上服务器续期后的 STOKEN
        later_cookie = rsps.calls[-1].request.headers["Cookie"]
        assert "STOKEN=newtoken1" in later_cookie
