import json
import os
import re

import requests
import urllib3

from dailycheckin import CheckIn

urllib3.disable_warnings()


class EnShanError(Exception):
    """恩山请求或解析失败。message 为面向用户的失败文案并进入通知内容。"""


class EnShan(CheckIn):
    name = "恩山无线论坛"

    # right.com.cn 的 WAF 对固定 UA/Accept 组合的请求容易返回 521（issues #569）。
    # 请求头纪律（PR 572）：页面 GET 按请求带浏览器常见 Accept，签到 POST 加 X-Requested-With；
    # UA 统一用 PR 562 的浏览器 UA；Cookie 改用 cookie jar 传递（PR 562），
    # 让 WAF 质询/续期下发的 Set-Cookie 能写回并在后续请求生效。
    _HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    _UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    )

    def __init__(self, check_item):
        self.check_item = check_item

    @staticmethod
    def get_formhash_from_page(session):
        """GET 签到页面并提取 formhash。Discuz 常见的 CSRF 字段。失败时抛 EnShanError"""
        try:
            response = session.get(
                "https://www.right.com.cn/forum/forum.php",
                headers={"Accept": EnShan._HTML_ACCEPT},
                timeout=15,
            )
        except requests.RequestException as e:
            raise EnShanError(f"请求签到页面失败: {e}") from e
        if response.status_code != 200:
            raise EnShanError(f"恩山返回 {response.status_code}，可能触发 WAF/需更新 Cookie")
        html = response.text
        # 常见两种位置：隐藏 input name="formhash" value="..." 或 js var formhash = '...'
        m = re.search(r'name=["\']formhash["\']\s+value=["\']([0-9a-fA-F]+)["\']', html)
        if not m:
            m = re.search(r"formhash\s*[:=]\s*['\"]([0-9a-fA-F]+)['\"]", html)
        if not m:
            # 有时 formhash 包含非十六进制字符，放宽匹配
            m = re.search(r'name=["\']formhash["\']\s+value=["\']([^"\']+)["\']', html)

        if not m:
            raise EnShanError("签到页面中未找到 formhash，可能触发 WAF/需更新 Cookie")
        return m.group(1)

    @staticmethod
    def sign(session, form_hash):
        msg = []
        payload = {"formhash": form_hash}
        response = session.post(
            "https://www.right.com.cn/forum/plugin.php?id=erling_qd:action&action=sign",
            headers={"X-Requested-With": "XMLHttpRequest"},
            data=payload,
            timeout=15,
        )
        try:
            data = response.json()
            if data.get("success"):
                continuous_days = data.get("continuous_days")
                msg = [
                    {
                        "name": "签到结果",
                        "value": data.get("message", "签到成功"),
                    },
                    {
                        "name": "连续签到",
                        "value": f"已连续签到{continuous_days}天",
                    },
                ]
            else:
                msg = [
                    {
                        "name": "签到结果",
                        "value": data.get("message", "签到失败"),
                    },
                ]
        except ValueError:
            msg = [
                {
                    "name": "签到结果",
                    "value": f"签到异常：{response.status_code}",
                }
            ]
        return msg

    @staticmethod
    def get_info(session):
        msg = []
        # 请求纳入 try 且不做 raise_for_status 裸抛（PR 557）：
        # 任何 WAF/网络事件只降级积分展示，不吞掉签到结果
        try:
            response = session.get(
                "https://www.right.com.cn/forum/home.php?mod=spacecp&ac=credit&showcredit=1",
                headers={"Accept": EnShan._HTML_ACCEPT},
                timeout=15,
            )
            if response.status_code != 200:
                return [
                    {
                        "name": "获取积分失败",
                        "value": f"恩山返回 {response.status_code}，可能触发 WAF/需更新 Cookie",
                    }
                ]
            html = response.text
            coin = re.findall("恩山币: </em>(.*?)&nbsp;", html)
            point = re.findall("<em>积分: </em>(.*?)<span", html)
            if coin and point:
                msg = [
                    {
                        "name": "恩山币",
                        "value": coin[0],
                    },
                    {
                        "name": "积分",
                        "value": point[0],
                    },
                ]
            else:
                # 页面无积分数据（WAF 质询页/登录页等）时降级提示，不再抛 IndexError
                msg = [
                    {
                        "name": "获取积分失败",
                        "value": "页面未包含积分数据，可能触发 WAF/需更新 Cookie",
                    }
                ]
        except Exception as e:
            msg = [
                {
                    "name": "获取代币失败",
                    "value": str(e),
                }
            ]
        return msg

    def main(self):
        cookie = self.check_item.get("cookie")
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": EnShan._UA,
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
                "Referer": "https://www.right.com.cn/forum/",
                "Upgrade-Insecure-Requests": "1",
                "Connection": "keep-alive",
            }
        )
        # Cookie 通过 cookie jar 传递（移除硬编码 Cookie 头，PR 562）
        for raw_part in (cookie or "").split(";"):
            part = raw_part.strip()
            if part and "=" in part:
                k, v = part.split("=", 1)
                session.cookies.set(k, v, domain=".right.com.cn", path="/")
        # formhash 获取失败提前返回明确文案，不带着失败状态继续签到（PR 557）
        try:
            form_hash = self.get_formhash_from_page(session=session)
        except EnShanError as e:
            return f"签到失败: {e}"
        msg = self.sign(session=session, form_hash=form_hash)
        msg += self.get_info(session=session)
        msg = "\n".join([f"{one.get('name')}: {one.get('value')}" for one in msg])
        return msg


if __name__ == "__main__":
    with open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"),
        encoding="utf-8",
    ) as f:
        datas = json.loads(f.read())
    _check_item = datas.get("ENSHAN", [])[0]
    print(EnShan(check_item=_check_item).main())
