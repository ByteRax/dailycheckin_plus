import json
import os
import re
from html import unescape
from urllib.parse import urlparse

import requests

from dailycheckin import CheckIn


class DiscuzError(Exception):
    """通用 Discuz 站点请求或解析失败。message 为面向用户的失败文案并进入通知内容。"""


class Discuz(CheckIn):
    name = "通用 Discuz 论坛"

    # Refs: Sitoi/dailycheckin#576 #556 #549 任意 Discuz 论坛签到。
    # Discuz 签到插件两大形态，按 sign_plugin 是否含冒号分发：
    #   - 冒号形式 "插件:模块"（默认 dsu_paulsign:sign，最常见签到插件，
    #     与 enshan 的 erling_qd:action 同族）：
    #       GET 插件页提取 formhash → POST plugin.php?id=<sign_plugin>&operation=qiandao 提交
    #   - 单段形式（zqlj_sign，#576 的 tekqart 例、fnnasclub 同族）：
    #       GET 插件页提取签到链接 token → GET plugin.php?id=<sign_plugin>&sign=<token> 签到
    DEFAULT_SIGN_PLUGIN = "dsu_paulsign:sign"

    _UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    )
    _HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    _TIMEOUT = 10

    # 签到响应 Message 的结果分类关键词（Discuz Message 弹窗/跳转页常见表述）
    _SUCCESS_MARKERS = ("签到成功", "打卡成功", "恭喜")
    _ALREADY_MARKERS = ("已经签到", "已签到", "已经打过卡", "已打卡", "请勿重复", "明天再来", "明日再来")
    # 插件页无签到链接时，用更严格的整词标记区分「已签到」与异常页，
    # 避免页面统计文案（如「今日已有 N 人签到」）造成误判
    _PAGE_ALREADY_MARKERS = ("今日已签到", "今日已打卡", "已经签到", "已经打过卡", "已经打卡")

    def __init__(self, check_item):
        self.check_item = check_item

    @classmethod
    def _request(cls, session, method, url, **kwargs):
        """统一请求入口: 网络异常/非 200 转为含状态码的明确失败。"""
        try:
            response = session.request(method, url, timeout=cls._TIMEOUT, **kwargs)
        except requests.RequestException as e:
            raise DiscuzError(f"请求失败 ({url}): {e}") from e
        if response.status_code != 200:
            raise DiscuzError(f"站点返回 {response.status_code} ({url})，可能 Cookie 已失效或站点异常")
        return response

    @staticmethod
    def _extract_formhash(html):
        """提取 Discuz CSRF formhash。常见两种位置: 隐藏 input 或 js 变量。"""
        m = re.search(r'name=["\']formhash["\']\s+value=["\']([0-9a-fA-F]+)["\']', html)
        if not m:
            m = re.search(r"formhash\s*[:=]\s*['\"]([0-9a-fA-F]+)['\"]", html)
        if not m:
            # 有时 formhash 包含非十六进制字符，放宽匹配
            m = re.search(r'name=["\']formhash["\']\s+value=["\']([^"\']+)["\']', html)
        return m.group(1) if m else None

    @staticmethod
    def _clean_text(fragment):
        text = re.sub(r"<[^>]+>", " ", fragment)
        text = unescape(text).replace("\xa0", " ")
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _extract_message(cls, html):
        """提取 Discuz Message 文案: 优先 inajax 响应的 CDATA, 其次整页提示框。找不到返回 None。"""
        for pattern in (
            r"<!\[CDATA\[(?P<text>.*?)\]\]>",
            r'id=["\']messagetext["\'][^>]*>(?P<text>.*?)</div>',
            r'class=["\']jump_c["\'][^>]*>(?P<text>.*?)</div>',
        ):
            m = re.search(pattern, html, re.S)
            if m:
                text = cls._clean_text(m.group("text"))
                if text:
                    return text
        return None

    @classmethod
    def _classify_message(cls, message):
        """签到结果分类。成功与未命中已知分类时透传原始 Message, 已签到归一为固定文案。"""
        if any(marker in message for marker in cls._SUCCESS_MARKERS):
            return message
        if any(marker in message for marker in cls._ALREADY_MARKERS):
            return "今日已签到"
        return message

    @classmethod
    def _build_result(cls, host, response):
        message = cls._extract_message(response.text)
        if not message:
            # 已提交但返回页无 Discuz Message，不伪造成功
            return [
                {"name": "站点", "value": host},
                {"name": "签到结果", "value": "已提交但未能确认结果"},
            ]
        return [
            {"name": "站点", "value": host},
            {"name": "签到结果", "value": cls._classify_message(message)},
        ]

    def _sign_via_post(self, session, base, host, plugin):
        """冒号插件形态: 插件页取 formhash 后 POST 提交签到。"""
        page = self._request(session, "GET", f"{base}/plugin.php?id={plugin}", headers={"Accept": self._HTML_ACCEPT})
        form_hash = self._extract_formhash(page.text)
        if not form_hash:
            raise DiscuzError("签到页面中未找到 formhash，可能 Cookie 已失效或站点改版")
        response = self._request(
            session,
            "POST",
            f"{base}/plugin.php?id={plugin}&operation=qiandao&infloat=1&inajax=1",
            headers={"X-Requested-With": "XMLHttpRequest"},
            # dsu_paulsign 的默认表单: 情感签到模式 + 默认表情文字
            data={"formhash": form_hash, "qdmode": "1", "fasttxt": "开心", "todaysay": ""},
        )
        return self._build_result(host, response)

    def _sign_via_get(self, session, base, host, plugin):
        """单段插件形态: 插件页取签到链接 token 后 GET 签到 (zqlj_sign 族)。"""
        page = self._request(session, "GET", f"{base}/plugin.php?id={plugin}", headers={"Accept": self._HTML_ACCEPT})
        html = page.text
        m = re.search(rf"plugin\.php\?id={re.escape(plugin)}&(?:amp;)?sign=([0-9a-zA-Z]+)", html)
        if not m:
            text = self._clean_text(html)
            if any(marker in text for marker in self._PAGE_ALREADY_MARKERS):
                return [
                    {"name": "站点", "value": host},
                    {"name": "签到结果", "value": "今日已签到"},
                ]
            raise DiscuzError("签到页面未找到签到链接，可能 Cookie 已失效或站点改版")
        response = self._request(
            session,
            "GET",
            f"{base}/plugin.php?id={plugin}&sign={m.group(1)}",
            headers={"Accept": self._HTML_ACCEPT},
        )
        return self._build_result(host, response)

    def main(self):
        url = str(self.check_item.get("url") or "").strip().rstrip("/")
        cookie = self.check_item.get("cookie")
        sign_plugin = str(self.check_item.get("sign_plugin") or self.DEFAULT_SIGN_PLUGIN).strip()
        if not url:
            return "签到失败: 缺少 url 配置"
        if not url.lower().startswith(("http://", "https://")):
            return f"签到失败: url 配置错误（需以 http:// 或 https:// 开头）: {url}"
        if not cookie:
            return "签到失败: 缺少 cookie 配置"
        host = urlparse(url).netloc
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": Discuz._UA,
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
                "Referer": f"{url}/",
                "Upgrade-Insecure-Requests": "1",
                "Connection": "keep-alive",
            }
        )
        # Cookie 经 cookie jar 传递（与 enshan PR 562 一致），站点下发的 Set-Cookie 可在后续请求生效
        for raw_part in str(cookie).split(";"):
            part = raw_part.strip()
            if part and "=" in part:
                k, v = part.split("=", 1)
                session.cookies.set(k, v, domain=host, path="/")
        try:
            if ":" in sign_plugin:
                msg = self._sign_via_post(session, base=url, host=host, plugin=sign_plugin)
            else:
                msg = self._sign_via_get(session, base=url, host=host, plugin=sign_plugin)
        except DiscuzError as e:
            return f"签到失败: {e}"
        return "\n".join([f"{one.get('name')}: {one.get('value')}" for one in msg])


if __name__ == "__main__":
    with open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"),
        encoding="utf-8",
    ) as f:
        datas = json.loads(f.read())
    _check_item = datas.get("DISCUZ", [])[0]
    print(Discuz(check_item=_check_item).main())
