import base64
import json
import os
import random
import threading
import time

import requests

from dailycheckin import CheckIn


class Niu(CheckIn):
    name = "小牛电动社区分享"

    APP_ID = "niu_ktdrr960"
    UA = (
        "manager/5.17.4 (android; ONEPLUS A5010 10);lang=zh-CN;"
        "clientIdentifier=Domestic;timezone=Asia/Shanghai;model=OnePlus_ONEPLUS A5010;"
        "deviceName=ONEPLUS A5010;ostype=android"
    )
    API_BASE = "https://app-api.niu.com"
    AUTH_URL = "https://account.niu.com/v3/api/oauth2/token"
    # 状态持久化目录（放在包外，避免升级时被删除）
    DEFAULT_STATE_DIR = os.path.join(os.path.expanduser("~"), ".dailycheckin")
    _STATE_LOCK = threading.Lock()

    def __init__(self, check_item):
        self.check_item = check_item
        self.account = (check_item.get("account") or "").strip()
        self.password = (check_item.get("password") or "").strip().lower()  # 密码 MD5（接口区分大小写，统一小写）
        self.app_id = check_item.get("app_id", self.APP_ID)
        self.state_file = check_item.get("state_file") or os.path.join(self.DEFAULT_STATE_DIR, "niu_token.json")
        self._state_key = self.account or self.password or "default"
        self.session = requests.session()
        self.session.headers.update({"user-agent": self.UA})

    # ---------- 基础工具 ----------
    @staticmethod
    def _jwt_exp(token):
        try:
            p = token.split(".")[1]
            p += "=" * (-len(p) % 4)
            return json.loads(base64.urlsafe_b64decode(p))["exp"]
        except Exception:
            return 0

    def _load_state(self):
        data = {}
        with self._STATE_LOCK:
            if os.path.exists(self.state_file):
                try:
                    with open(self.state_file, encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    data = {}
        return data.get(self._state_key, {})

    def _save_state(self, state):
        with self._STATE_LOCK:
            data = {}
            if os.path.exists(self.state_file):
                try:
                    with open(self.state_file, encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    data = {}
            data[self._state_key] = state
            state_dir = os.path.dirname(self.state_file)
            if state_dir:
                os.makedirs(state_dir, exist_ok=True)
            tmp_file = self.state_file + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, self.state_file)

    # ---------- 登录 / 刷新 ----------
    def _oauth(self, params):
        resp = self.session.post(
            self.AUTH_URL,
            data=params,
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "token": "tokenExperienceMode",
                "x-no-encrypt": "1",
            },
            timeout=30,
        )
        return resp.json()

    def _login(self):
        data = self._oauth(
            {
                "password": self.password,
                "grant_type": "password",
                "scope": "base",
                "app_id": self.app_id,
                "account": self.account,
            }
        )
        if data.get("status") != 0:
            raise RuntimeError(f"登录失败: {data}")
        return data["data"]["token"]

    def _refresh(self, refresh_token):
        data = self._oauth(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "app_id": self.app_id,
                "scope": "base",
            }
        )
        if data.get("status") != 0:
            raise RuntimeError(f"刷新失败: {data}")
        return data["data"]["token"]

    def _ensure_token(self, state):
        now = int(time.time())
        access_token = state.get("access_token")
        refresh_token = state.get("refresh_token")

        if access_token and self._jwt_exp(access_token) > now + 86400:
            return access_token

        if refresh_token:
            try:
                tok = self._refresh(refresh_token)
                state["access_token"] = tok["access_token"]
                state["refresh_token"] = tok.get("refresh_token", refresh_token)
                state["access_exp"] = tok.get("token_expires_in")
                self._save_state(state)
                return state["access_token"]
            except Exception as e:
                print(f"[niu] refresh_token 刷新失败: {e}")

        tok = self._login()
        state["access_token"] = tok["access_token"]
        state["refresh_token"] = tok["refresh_token"]
        state["access_exp"] = tok.get("token_expires_in")
        self._save_state(state)
        return state["access_token"]

    # ---------- 社区分享 ----------
    def _get_posts(self, access_token, page=1):
        resp = self.session.get(
            f"{self.API_BASE}/community/api/posts/recommend/list",
            params={
                "page": page,
                "version": 0,
                "page_size": 20,
                "_": int(time.time() * 1000),
            },
            headers={"token": access_token, "content-type": "application/json"},
            timeout=30,
        )
        return resp.json().get("data", {}).get("items", [])

    def _share(self, access_token, pid):
        resp = self.session.post(
            f"{self.API_BASE}/community/api/posts/shares",
            json={"id": pid},
            headers={
                "token": access_token,
                "content-type": "application/json; charset=utf-8",
            },
            timeout=30,
        )
        return resp.json()

    def _points(self, access_token):
        resp = self.session.get(
            f"{self.API_BASE}/v5/points/index",
            headers={"token": access_token, "content-type": "application/json"},
            timeout=30,
        )
        return resp.json().get("data", {}).get("userPoints")

    def main(self):
        state = self._load_state()
        access_token = self._ensure_token(state)

        shared = set(state.get("shared", []))
        by_date = state.get("shared_by_date")
        if isinstance(by_date, dict):
            for ids in by_date.values():
                shared.update(ids)
            state.pop("shared_by_date", None)

        try:
            points_before = self._points(access_token)
        except Exception:
            points_before = None

        targets = []
        page = 1
        while len(targets) < 2 and page <= 20:
            items = self._get_posts(access_token, page)
            if not items:
                break
            for it in items:
                pid = it["id"]
                if pid not in shared and pid not in targets:
                    targets.append(pid)
                    if len(targets) == 2:
                        break
            page += 1

        if not targets:
            account = str(self.account)
            account_masked = f"{account[:3]}****{account[-4:]}" if len(account) > 7 else account
            return f"账号: {account_masked}\n没有可分享的新帖子"

        failures = []
        for i, pid in enumerate(targets):
            if i > 0:
                time.sleep(random.randint(3, 8))
            result = self._share(access_token, pid)
            if result.get("status") == 0:
                shared.add(pid)
                state["shared"] = sorted(shared)
                self._save_state(state)
            else:
                failures.append(f"{pid}: {result}")

        try:
            points_after = self._points(access_token)
        except Exception:
            points_after = None

        if points_before is not None and points_after is not None:
            change = points_after - points_before
            sign = "+" if change > 0 else ""
            msg = f"积分变化: {sign}{change}"
        else:
            msg = "分享成功"

        if failures:
            msg += f"\n分享失败: {failures}"

        if len(targets) < 2:
            msg += f"\n仅找到 {len(targets)} 个未分享帖子"

        account = str(self.account)
        account_masked = f"{account[:3]}****{account[-4:]}" if len(account) > 7 else account
        return f"账号: {account_masked}\n{msg}"


if __name__ == "__main__":
    with open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "config.json"),
        encoding="utf-8",
    ) as f:
        datas = json.loads(f.read())
    _check_item = datas.get("NIU", [])[0]
    print(Niu(check_item=_check_item).main())
