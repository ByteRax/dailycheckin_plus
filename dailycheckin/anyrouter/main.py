import json
import os
import re

import requests

from dailycheckin import CheckIn


class AnyRouter(CheckIn):
    name = "AnyRouter"

    def __init__(self, check_item):
        self.check_item = check_item

    @staticmethod
    def _parse_cookie(cookie_data):
        if isinstance(cookie_data, dict):
            return cookie_data
        cookie_data = re.sub(r"^\s*cookie\s*:\s*", "", str(cookie_data), flags=re.I)
        cookies = {}
        for part in (p.strip() for p in cookie_data.split(";")):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            cookies[key.strip()] = value.strip()
        return cookies

    @staticmethod
    def _cookie_header(cookies):
        return "; ".join(f"{key}={value}" for key, value in cookies.items() if value)

    @staticmethod
    def _normalize_cookie_header(cookie_data):
        if isinstance(cookie_data, dict):
            return AnyRouter._cookie_header(cookie_data)
        cookie_data = re.sub(r"^\s*cookie\s*:\s*", "", str(cookie_data), flags=re.I)
        return "; ".join(item.strip() for item in cookie_data.split(";") if item.strip())

    @staticmethod
    def _response_summary(response):
        content_type = response.headers.get("content-type", "") or "未知"
        text = (response.text or "").strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) > 120:
            text = f"{text[:120]}..."
        return f"响应不是 JSON，Content-Type: {content_type}，Body: {text or '空'}"

    @staticmethod
    def _parse_sign_result(response):
        data = response.json()
        if response.status_code == 401 and not data:
            return False, "登录态无效，请检查 cookie/cookies 与 user_id/api_user 是否匹配或已过期"
        success = bool(data.get("success"))
        detail = data.get("message", "") or "无"
        return success, detail

    @classmethod
    def sign(cls, session, user_id, cookie=""):
        url = "https://anyrouter.top/api/user/sign_in"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-store",
            "Origin": "https://anyrouter.top",
            "Referer": "https://anyrouter.top/console",
            "New-Api-User": str(user_id),
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.0.0 Safari/537.36"
            ),
            "Sec-Ch-Ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Cookie": cls._normalize_cookie_header(cookie),
            "Accept-Encoding": "gzip",
        }
        response = session.post(url=url, headers=headers, timeout=30)

        request_id = response.headers.get("x-oneapi-request-id", "")
        status_code = response.status_code
        msg = [
            {"name": "请求状态码", "value": status_code},
            {"name": "请求ID", "value": request_id or "无"},
        ]

        try:
            success, detail = cls._parse_sign_result(response)
            msg += [
                {"name": "签到结果", "value": "成功" if success else "失败"},
                {"name": "返回信息", "value": detail},
            ]
        except Exception:
            msg += [
                {"name": "签到结果", "value": "失败"},
                {"name": "返回信息", "value": cls._response_summary(response)},
            ]
        return msg

    def main(self):
        cookie = self.check_item.get("cookie") or self.check_item.get("cookies", "")
        user_id = self.check_item.get("user_id") or self.check_item.get("api_user", "")
        if not cookie or not user_id:
            msg = [
                {"name": "帐号信息", "value": "配置错误"},
                {"name": "签到结果", "value": "缺少 cookie/cookies 或 user_id/api_user"},
            ]
            return "\n".join([f"{one.get('name')}: {one.get('value')}" for one in msg])

        session = requests.session()
        msg = self.sign(session=session, user_id=user_id, cookie=cookie)
        return "\n".join([f"{one.get('name')}: {one.get('value')}" for one in msg])


if __name__ == "__main__":
    with open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"),
        encoding="utf-8",
    ) as f:
        datas = json.loads(f.read())
    _check_item = datas.get("ANYROUTER", [])[0]
    print(AnyRouter(check_item=_check_item).main())
