import json
import os
import re
from urllib.parse import urlparse

import requests

from dailycheckin import CheckIn


class Custom(CheckIn):
    """通用自定义 HTTP 签到: 用户自行抓包请求地址/Cookie 后按任务直配。

    面向 #576 例二等非 Discuz 形态站点(如 WordPress 主题自有 JSON/表单接口)。
    请求 method 与 body 由用户自负其责, 本服务不做任何校验与自动重试——
    一次请求, 成败一次判清。
    """

    name = "自定义 HTTP 签到"

    # Refs: Sitoi/dailycheckin#576 任意第三方自定义签到（例二 gkinto.com WordPress
    # POST user.php action=user.checkin 形态）；Discuz 系论坛请用 DISCUZ 服务。
    _UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    )
    _TIMEOUT = 10
    _SUPPORTED_METHODS = ("GET", "POST")
    # 失败时响应摘要的安全上限: 只取前 120 字符
    _SNIPPET_MAX = 120
    # 响应文本可能含敏感信息: ≥20 位连续字母数字视为 token 串, 脱敏为 ***
    _TOKEN_RE = re.compile(r"[0-9A-Za-z]{20,}")

    def __init__(self, check_item):
        self.check_item = check_item

    @classmethod
    def _snippet(cls, text):
        """失败文案里的响应摘要: 先脱敏长 token, 再截断到前 120 字符。"""
        return cls._TOKEN_RE.sub("***", text)[: cls._SNIPPET_MAX]

    @staticmethod
    def _compile(pattern, label):
        """编译用户正则。语法错误或类型错误时抛 ValueError, 由调用方转为配置错误文案。"""
        try:
            return re.compile(pattern)
        except re.error as e:
            raise ValueError(f"{label} 正则语法错误: {e}") from e
        except TypeError as e:
            raise ValueError(f"{label} 正则必须是字符串: {e}") from e

    def main(self):
        url = str(self.check_item.get("url") or "").strip()
        if not url:
            return "签到失败: 缺少 url 配置"
        if not url.lower().startswith(("http://", "https://")):
            return f"签到失败: 配置错误: url 需以 http:// 或 https:// 开头: {url}"
        method = str(self.check_item.get("method") or "GET").strip().upper()
        if method not in self._SUPPORTED_METHODS:
            return f"签到失败: 配置错误: method 仅支持 GET/POST: {method}"
        task_name = str(self.check_item.get("name") or "").strip() or urlparse(url).netloc

        already_re = success_re = None
        try:
            already_pattern = self.check_item.get("already")
            success_pattern = self.check_item.get("success")
            if already_pattern:
                already_re = self._compile(already_pattern, "already")
            if success_pattern:
                success_re = self._compile(success_pattern, "success")
        except ValueError as e:
            return f"签到失败: 配置错误: {e}"

        # 基础浏览器头与用户自定义 headers 合并（用户头优先, 如 Content-Type/Authorization/自定义 UA）;
        # cookie 配置作为 Cookie 头并入
        headers = {
            "User-Agent": self._UA,
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Connection": "keep-alive",
        }
        user_headers = self.check_item.get("headers")
        if isinstance(user_headers, dict):
            headers.update({str(k): str(v) for k, v in user_headers.items()})
        if cookie := self.check_item.get("cookie"):
            headers["Cookie"] = str(cookie)
        body = self.check_item.get("body")

        try:
            # 单次请求, 不做重试（requests 默认无重试, 也未挂载 Retry adapter）
            response = requests.request(method, url, headers=headers, data=body, timeout=self._TIMEOUT)
        except requests.RequestException as e:
            # 回显 URL 时去掉 query（用户可能把 token 放在 ?token=…），异常文本里再补打码
            shown = url.split("?", 1)[0]
            return f"签到失败: 请求异常 ({shown}): {type(e).__name__}"

        text = response.text
        if already_re is not None and already_re.search(text):
            result = "今日已签到"
        elif success_re is not None:
            if success_re.search(text):
                result = "签到成功"
            else:
                result = f"签到失败: HTTP {response.status_code}, 响应: {self._snippet(text)}"
        elif 200 <= response.status_code < 300:
            result = "签到成功"
        else:
            result = f"签到失败: HTTP {response.status_code}, 响应: {self._snippet(text)}"
        return "\n".join([f"任务: {task_name}", f"签到结果: {result}"])


if __name__ == "__main__":
    with open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"),
        encoding="utf-8",
    ) as f:
        datas = json.loads(f.read())
    _check_item = datas.get("CUSTOM", [])[0]
    print(Custom(check_item=_check_item).main())
