import re
import time

import requests
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA

from dailycheckin import CheckIn


class Cloud189Error(Exception):
    """携带用户可读文案的模块异常, 消息中不得包含密码与请求体。"""


class Cloud189(CheckIn):
    name = "天翼云盘"
    """
    天翼云盘个人签到任务(账密型)。

    2021 年旧模块随架构迁移被删(commit 8f05f36), 本模块按现代协议重写,
    协议流程参照 MIT 许可的 wes-lin/cloud189-sdk(2026-10 快照):
    encryptConf.do 取 RSA 公钥 -> unifyLoginForPC.action 取登录参数 ->
    loginSubmit.do 账密登录 -> getSessionForPC.action 换 sessionKey ->
    userSign.action 签到(sessionKey 参数鉴权, 无需 Signature 头)。
    """

    AUTH_URL = "https://open.e.189.cn"
    WEB_URL = "https://cloud.189.cn"
    API_URL = "https://api.cloud.189.cn"
    APP_ID = "8025431004"
    CLIENT_TYPE = "10020"
    RETURN_URL = "https://m.cloud.189.cn/zhuanti/2020/loginErrorPc/index.html"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/87.0.4280.88 Safari/537.36"
    )
    # 签到接口的移动客户端参数(对应 cloud189-sdk CloudClient 的 config)
    SIGN_VERSION = "9.0.6"
    SIGN_MODEL = "KB2000"

    def __init__(self, check_item: dict):
        self.check_item = check_item
        self.username = str(check_item.get("username") or "")
        self.password = str(check_item.get("password") or "")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.USER_AGENT,
                "Accept": "application/json;charset=UTF-8",
            }
        )

    @staticmethod
    def _rsa_encrypt(pub_key: str, text: str) -> str:
        """RSA/PKCS1 v1.5 加密, 输出 hex(与 cloud189-sdk util.ts rsaEncrypt 同规格)。"""
        pem = f"-----BEGIN PUBLIC KEY-----\n{pub_key}\n-----END PUBLIC KEY-----"
        cipher = PKCS1_v1_5.new(RSA.import_key(pem))
        return cipher.encrypt(text.encode("utf-8")).hex()

    def _get_encrypt_conf(self):
        """POST encryptConf.do 获取 RSA 公钥与前缀。"""
        try:
            response = self.session.post(f"{self.AUTH_URL}/api/logbox/config/encryptConf.do", timeout=10)
        except requests.RequestException as e:
            raise Cloud189Error(f"获取公钥失败: 网络异常({type(e).__name__})")
        if response.status_code != 200:
            raise Cloud189Error(f"获取公钥失败: HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise Cloud189Error("获取公钥失败: 响应格式异常")
        conf = data.get("data") if isinstance(data, dict) else None
        pub_key = conf.get("pubKey") if isinstance(conf, dict) else None
        pre = conf.get("pre") if isinstance(conf, dict) else None
        if not pub_key or pre is None:
            msg = data.get("msg") if isinstance(data, dict) else None
            raise Cloud189Error(f"获取公钥失败: {msg or '响应缺少公钥字段'}")
        return pub_key, pre

    def _get_login_form(self):
        """GET unifyLoginForPC.action, 从登录页 HTML 提取登录参数。"""
        try:
            response = self.session.get(
                f"{self.WEB_URL}/api/portal/unifyLoginForPC.action",
                params={
                    "appId": self.APP_ID,
                    "clientType": self.CLIENT_TYPE,
                    "returnURL": self.RETURN_URL,
                    "timeStamp": int(time.time() * 1000),
                },
                timeout=10,
            )
        except requests.RequestException as e:
            raise Cloud189Error(f"获取登录参数失败: 网络异常({type(e).__name__})")
        if response.status_code != 200:
            raise Cloud189Error(f"获取登录参数失败: HTTP {response.status_code}")
        html = response.text
        patterns = {
            "captchaToken": r"'captchaToken' value='(.+?)'",
            "lt": r'lt = "(.+?)"',
            "paramId": r'paramId = "(.+?)"',
            "reqId": r'reqId = "(.+?)"',
        }
        form = {}
        for name, pattern in patterns.items():
            match = re.search(pattern, html)
            if not match:
                raise Cloud189Error(f"获取登录参数失败: 登录页缺少 {name}")
            form[name] = match.group(1)
        return form

    def _login_by_password(self):
        """账密登录, 返回 loginSubmit 下发的 toUrl。"""
        pub_key, pre = self._get_encrypt_conf()
        login_form = self._get_login_form()
        try:
            username_cipher = self._rsa_encrypt(pub_key, self.username)
            password_cipher = self._rsa_encrypt(pub_key, self.password)
        except Exception:
            raise Cloud189Error("密码加密失败: 公钥格式无法解析")
        data = {
            "appKey": self.APP_ID,
            "accountType": "02",
            "validateCode": "",
            "captchaToken": login_form["captchaToken"],
            "dynamicCheck": "FALSE",
            "clientType": "1",
            "cb_SaveName": "3",
            "isOauth2": "false",
            "returnUrl": self.RETURN_URL,
            "paramId": login_form["paramId"],
            "userName": f"{pre}{username_cipher}",
            "password": f"{pre}{password_cipher}",
        }
        try:
            response = self.session.post(
                f"{self.AUTH_URL}/api/logbox/oauth2/loginSubmit.do",
                data=data,
                headers={
                    "Referer": self.AUTH_URL,
                    "lt": login_form["lt"],
                    "REQID": login_form["reqId"],
                },
                timeout=10,
            )
        except requests.RequestException as e:
            raise Cloud189Error(f"登录失败: 网络异常({type(e).__name__})")
        if response.status_code == 429:
            raise Cloud189Error("登录失败: 请求过于频繁(疑似触发风控), 请稍后再试或更换网络环境")
        if response.status_code != 200:
            raise Cloud189Error(f"登录失败: HTTP {response.status_code}")
        try:
            login_result = response.json()
        except ValueError:
            raise Cloud189Error("登录失败: 响应格式异常")
        if login_result.get("result") != 0:
            msg = str(login_result.get("msg") or f"result={login_result.get('result')}")
            if any(keyword in msg for keyword in ("验证码", "锁定", "频繁")):
                msg += "(疑似触发风控, 请稍后再试或更换网络环境)"
            raise Cloud189Error(f"登录失败: {msg}")
        to_url = login_result.get("toUrl")
        if not to_url:
            raise Cloud189Error("登录失败: 响应缺少跳转地址")
        return to_url

    def _get_session_key(self, to_url: str) -> str:
        """POST getSessionForPC.action, 用 toUrl 换取 sessionKey。"""
        params = {
            "appId": self.APP_ID,
            "clientType": "TELEPC",
            "version": "6.2",
            "channelId": "web_cloud.189.cn",
            "rand": int(time.time() * 1000),
            "redirectURL": to_url,
        }
        try:
            response = self.session.post(f"{self.API_URL}/getSessionForPC.action", params=params, timeout=10)
        except requests.RequestException as e:
            raise Cloud189Error(f"获取会话失败: 网络异常({type(e).__name__})")
        if response.status_code != 200:
            raise Cloud189Error(f"获取会话失败: HTTP {response.status_code}")
        try:
            session_data = response.json()
        except ValueError:
            raise Cloud189Error("获取会话失败: 响应格式异常")
        session_key = session_data.get("sessionKey")
        if not session_key:
            msg = session_data.get("res_message") or "响应缺少 sessionKey"
            raise Cloud189Error(f"获取会话失败: {msg}")
        return session_key

    def _user_sign(self, session_key: str):
        """GET userSign.action 签到(sessionKey 参数鉴权)。"""
        params = {
            "rand": int(time.time() * 1000),
            "clientType": "TELEANDROID",
            "version": self.SIGN_VERSION,
            "model": self.SIGN_MODEL,
            "sessionKey": session_key,
        }
        try:
            response = self.session.get(f"{self.WEB_URL}/mkt/userSign.action", params=params, timeout=10)
        except requests.RequestException as e:
            raise Cloud189Error(f"签到失败: 网络异常({type(e).__name__})")
        if response.status_code != 200:
            raise Cloud189Error(f"签到失败: HTTP {response.status_code}")
        try:
            sign_data = response.json()
        except ValueError:
            raise Cloud189Error("签到失败: 响应格式异常")
        if "isSign" not in sign_data:
            error_msg = sign_data.get("errorMsg") or sign_data.get("res_message") or "响应缺少签到结果字段"
            raise Cloud189Error(f"签到失败: {error_msg}")
        return sign_data

    @staticmethod
    def _mask_username(username: str) -> str:
        if not username:
            return "未配置"
        if len(username) <= 5:
            return "*" * len(username)
        return f"{username[:3]}****{username[-2:]}"

    def _build_msg(self, result: str) -> str:
        msg = [
            {"name": "帐号信息", "value": self._mask_username(self.username)},
            {"name": "签到结果", "value": result},
        ]
        return "\n".join([f"{one.get('name')}: {one.get('value')}" for one in msg])

    def main(self):
        if not self.username or not self.password:
            return self._build_msg("账号或密码未配置")
        try:
            to_url = self._login_by_password()
            session_key = self._get_session_key(to_url)
            sign_data = self._user_sign(session_key)
        except Cloud189Error as e:
            return self._build_msg(str(e))
        except Exception as e:
            # 兜底: 未预期异常只上抛类型名, 确保不携带密码或请求体
            return self._build_msg(f"签到失败: {type(e).__name__}")
        if sign_data.get("isSign"):
            return self._build_msg("今日已签到, 无新增奖励")
        return self._build_msg(f"签到成功, 获得 {sign_data.get('netdiskBonus', 0)}M 空间")


if __name__ == "__main__":
    import json
    import os

    with open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"),
        encoding="utf-8",
    ) as f:
        datas = json.loads(f.read())
    _check_item = datas.get("CLOUD189", [])[0]
    print(Cloud189(check_item=_check_item).main())
