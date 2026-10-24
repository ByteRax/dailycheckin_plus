"""小米运动 mimotion 离线回归测试。

对应上游 issues #533/#565: 保存并复用 login (account.zepp.com/v2/client/login)
返回的 app_token, 跳过每账号两步登录, 绕开单 IP 登录限流(429)。
全部 HTTP 请求经 responses mock, 无真实凭据、无网络访问; 配置文件用 tmp_path 隔离。
"""

import json
import os
import re

import pytest
import requests
import responses

from dailycheckin.mimotion.main import MiMotion

PHONE_0 = "13800000001"
PHONE_1 = "13800000002"
LOGIN_STEP1_URL_0 = f"https://api-user.zepp.com/registrations/+86{PHONE_0}/tokens"
LOGIN_STEP1_URL_1 = f"https://api-user.zepp.com/registrations/+86{PHONE_1}/tokens"
LOGIN_STEP2_URL = "https://account.zepp.com/v2/client/login"
UPLOAD_URL = re.compile(r"https://api-mifit-cn\.huami\.com/v1/data/band_data\.json.*")


def _write_config(tmp_path, accounts):
    config = {
        "MERGE_PUSH": "",
        "MIMOTION": accounts,
        "ENSHAN": [{"cookie": "keepme=1"}],
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    return path


def _read_config(config_path):
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def _load_account(config_path, index=0):
    return _read_config(config_path)["MIMOTION"][index]


def _mock_login_ok(mock, app_token="token-new", user_id=12345, phone=PHONE_0):
    step1_url = LOGIN_STEP1_URL_1 if phone == PHONE_1 else LOGIN_STEP1_URL_0
    mock.add(responses.POST, step1_url, json={"access": "access-code"})
    mock.add(
        responses.POST,
        LOGIN_STEP2_URL,
        json={"token_info": {"login_token": "lt-0", "user_id": user_id, "app_token": app_token}},
    )


def _mock_upload_ok(mock):
    mock.add(responses.POST, UPLOAD_URL, json={"code": 1, "message": "success"})


def _upload_calls(mock):
    return [call for call in mock.calls if "api-mifit" in call.request.url]


@pytest.fixture
def rsps():
    # responses 0.23 起 assert_all_requests_are_fired 默认为 True,
    # 用例断言失败时未发出的 mock 会级联成 teardown error, 这里显式关闭
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


class TestAppTokenReuse:
    def test_valid_token_skips_login_and_keeps_config(self, tmp_path, monkeypatch, rsps):
        """配置含有效 app_token: 直接用它提交, 不请求 zepp 登录接口, 配置文件原样。"""
        config_path = _write_config(
            tmp_path,
            [
                {
                    "phone": PHONE_0,
                    "password": "pass0",
                    "min_step": 10000,
                    "max_step": 20000,
                    "app_token": "token-saved",
                    "user_id": 12345,
                }
            ],
        )
        monkeypatch.chdir(tmp_path)
        before = config_path.read_text(encoding="utf-8")
        _mock_upload_ok(rsps)

        msg = MiMotion(check_item=_load_account(config_path)).main()

        assert "修改信息: success" in msg
        # 未调用任何 zepp 登录接口（时间戳接口未 mock, 走本地时间兜底）
        assert rsps.calls and all("zepp.com" not in call.request.url for call in rsps.calls)
        uploads = _upload_calls(rsps)
        assert len(uploads) == 1
        assert uploads[0].request.headers["apptoken"] == "token-saved"
        assert config_path.read_text(encoding="utf-8") == before

    @pytest.mark.parametrize(
        "status, body",
        [
            (401, {"code": 1, "message": "ok"}),
            (200, {"code": 401, "message": "re login"}),
            (200, {"code": 0, "message": "app token is expired"}),
        ],
        ids=["http-401", "code-401", "token-message"],
    )
    def test_invalid_token_relogins_and_writes_back_new_token(self, tmp_path, monkeypatch, rsps, status, body):
        """保存的 token 失效(401/token 相关错误): 重新走完整登录, 写回新 token, 并用新 token 重试提交。"""
        config_path = _write_config(
            tmp_path,
            [{"phone": PHONE_0, "password": "pass0", "app_token": "token-expired", "user_id": 12345}],
        )
        monkeypatch.chdir(tmp_path)
        upload_count = {"n": 0}

        def upload_callback(request):
            upload_count["n"] += 1
            if upload_count["n"] == 1:
                return (status, {}, json.dumps(body))
            return (200, {}, json.dumps({"code": 1, "message": "success"}))

        rsps.add_callback(responses.POST, UPLOAD_URL, callback=upload_callback)
        _mock_login_ok(rsps, app_token="token-new", user_id=12345)

        msg = MiMotion(check_item=_load_account(config_path)).main()

        assert "修改信息: success" in msg
        uploads = _upload_calls(rsps)
        assert len(uploads) == 2
        assert uploads[0].request.headers["apptoken"] == "token-expired"
        assert uploads[1].request.headers["apptoken"] == "token-new"
        account = _read_config(config_path)["MIMOTION"][0]
        assert account["app_token"] == "token-new"
        assert account["user_id"] == "12345"

    def test_token_without_user_id_falls_back_to_login(self, tmp_path, monkeypatch, rsps):
        """只配 app_token 没配 user_id(提交步数必需): 回退完整登录并补写 user_id。"""
        config_path = _write_config(tmp_path, [{"phone": PHONE_0, "password": "pass0", "app_token": "token-lonely"}])
        monkeypatch.chdir(tmp_path)
        _mock_login_ok(rsps, app_token="token-fresh", user_id=56789)
        _mock_upload_ok(rsps)

        msg = MiMotion(check_item=_load_account(config_path)).main()

        assert "修改信息: success" in msg
        uploads = _upload_calls(rsps)
        assert len(uploads) == 1
        assert uploads[0].request.headers["apptoken"] == "token-fresh"
        account = _read_config(config_path)["MIMOTION"][0]
        assert account["app_token"] == "token-fresh"
        assert account["user_id"] == "56789"


class TestWriteBackSafety:
    def test_first_run_persists_app_token_and_keeps_other_fields(self, tmp_path, monkeypatch, rsps):
        """无 token 用户首跑: 登录成功后 config.json 多出 app_token/user_id, 其余字段/服务原样。"""
        config_path = _write_config(
            tmp_path,
            [{"phone": PHONE_0, "password": "pass0", "min_step": 11111, "max_step": 22222}],
        )
        monkeypatch.chdir(tmp_path)
        _mock_login_ok(rsps, app_token="token-fresh", user_id=12345)
        _mock_upload_ok(rsps)

        msg = MiMotion(check_item=_load_account(config_path)).main()

        assert "修改信息: success" in msg
        data = _read_config(config_path)
        assert data["MIMOTION"][0] == {
            "phone": PHONE_0,
            "password": "pass0",
            "min_step": 11111,
            "max_step": 22222,
            "app_token": "token-fresh",
            "user_id": "12345",
        }
        assert data["ENSHAN"] == [{"cookie": "keepme=1"}]
        assert data["MERGE_PUSH"] == ""
        assert not (tmp_path / "config.json.tmp").exists()

    def test_write_back_only_touches_target_account(self, tmp_path, monkeypatch, rsps):
        """多账号配置只改当前账号(按索引匹配), 其余账号与其他服务配置不动。"""
        config_path = _write_config(
            tmp_path,
            [
                {"phone": PHONE_0, "password": "pass0"},
                {"phone": PHONE_1, "password": "pass1"},
            ],
        )
        monkeypatch.chdir(tmp_path)
        _mock_login_ok(rsps, app_token="token-acct1", user_id=67890, phone=PHONE_1)
        _mock_upload_ok(rsps)

        msg = MiMotion(check_item=_load_account(config_path, 1)).main()

        assert "修改信息: success" in msg
        data = _read_config(config_path)
        assert data["MIMOTION"][0] == {"phone": PHONE_0, "password": "pass0"}
        assert data["MIMOTION"][1] == {
            "phone": PHONE_1,
            "password": "pass1",
            "app_token": "token-acct1",
            "user_id": "67890",
        }

    def test_replace_failure_keeps_original_file_and_warns(self, tmp_path, monkeypatch, rsps, capsys):
        """原子替换失败: 原配置文件必须完好, 清理 tmp, 打印警告, 提交结果照常上报。"""
        config_path = _write_config(tmp_path, [{"phone": PHONE_0, "password": "pass0"}])
        monkeypatch.chdir(tmp_path)
        _mock_login_ok(rsps)
        _mock_upload_ok(rsps)

        def _boom(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", _boom)
        before = config_path.read_text(encoding="utf-8")

        msg = MiMotion(check_item=_load_account(config_path)).main()

        assert "修改信息: success" in msg
        assert config_path.read_text(encoding="utf-8") == before
        assert not (tmp_path / "config.json.tmp").exists()
        assert "写回" in capsys.readouterr().out

    def test_account_not_found_on_disk_skips_write(self, tmp_path, monkeypatch, rsps, capsys):
        """运行期间配置被改动(快照匹配不到账号): 跳过写回并警告, 不误写他人。"""
        config_path = _write_config(tmp_path, [{"phone": PHONE_0, "password": "pass0"}])
        monkeypatch.chdir(tmp_path)
        _mock_login_ok(rsps)
        _mock_upload_ok(rsps)

        account = _load_account(config_path)
        data = _read_config(config_path)
        data["MIMOTION"][0]["password"] = "changed-during-run"
        config_path.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
        changed = config_path.read_text(encoding="utf-8")

        MiMotion(check_item=account).main()

        assert config_path.read_text(encoding="utf-8") == changed
        assert "写回" in capsys.readouterr().out

    def test_missing_config_file_no_crash(self, tmp_path, monkeypatch, rsps):
        """找不到 config.json(未配置/只读场景): 静默跳过回写, 提交结果正常返回。"""
        monkeypatch.chdir(tmp_path)
        _mock_login_ok(rsps)
        _mock_upload_ok(rsps)

        msg = MiMotion(check_item={"phone": PHONE_0, "password": "pass0"}).main()

        assert "修改信息: success" in msg
        assert not (tmp_path / "config.json.tmp").exists()

    def test_login_rate_limited_429_no_write_back(self, tmp_path, monkeypatch, rsps):
        """登录被限流(#533 主诉): 报登陆失败, 不写回任何内容。"""
        config_path = _write_config(tmp_path, [{"phone": PHONE_0, "password": "pass0"}])
        monkeypatch.chdir(tmp_path)
        rsps.add(responses.POST, LOGIN_STEP1_URL_0, status=429, body="too many requests")
        before = config_path.read_text(encoding="utf-8")

        msg = MiMotion(check_item=_load_account(config_path)).main()

        assert "登陆失败" in msg
        assert config_path.read_text(encoding="utf-8") == before
        assert _upload_calls(rsps) == []


class TestRequestTimeouts:
    def test_all_requests_use_timeout(self, tmp_path, monkeypatch, rsps):
        """时间戳/两步登录/提交步数全链路请求必须带 timeout=10。"""
        config_path = _write_config(
            tmp_path,
            [{"phone": PHONE_0, "password": "pass0", "app_token": "token-expired", "user_id": 12345}],
        )
        monkeypatch.chdir(tmp_path)
        upload_count = {"n": 0}

        def upload_callback(request):
            upload_count["n"] += 1
            if upload_count["n"] == 1:
                return (401, {}, json.dumps({"code": 401, "message": "token is invalid"}))
            return (200, {}, json.dumps({"code": 1, "message": "success"}))

        rsps.add_callback(responses.POST, UPLOAD_URL, callback=upload_callback)
        _mock_login_ok(rsps)

        captured = []
        original_request = requests.Session.request

        def recording_request(session, *args, **kwargs):
            captured.append((kwargs.get("method"), kwargs.get("url"), kwargs.get("timeout")))
            return original_request(session, *args, **kwargs)

        monkeypatch.setattr(requests.Session, "request", recording_request)

        msg = MiMotion(check_item=_load_account(config_path)).main()

        assert "修改信息: success" in msg
        assert captured, "没有捕获到任何请求"
        assert all(timeout == 10 for _, _, timeout in captured), captured
        urls = " ".join(url for _, url, _ in captured if url)
        assert "acs.m.taobao.com" in urls  # 时间戳接口
        assert "api-user.zepp.com" in urls  # 登录第一步
        assert "account.zepp.com" in urls  # 登录第二步
        assert "api-mifit-cn.huami.com" in urls  # 提交步数
