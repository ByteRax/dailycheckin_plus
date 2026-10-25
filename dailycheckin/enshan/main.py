import json
import os
import re

import requests
import urllib3

from dailycheckin import CheckIn

urllib3.disable_warnings()


class EnShan(CheckIn):
    name = "恩山无线论坛"

    # 说明：right.com.cn 站点存在 WAF；实测部分 UA/Accept 组合会触发 521，
    # 因此避免在 Session 级别强行覆盖 UA/Accept，GET 页面时使用浏览器常见的 Accept(text/html)。
    _HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"

    def __init__(self, check_item):
        self.check_item = check_item

    @staticmethod
    def get_formhash_from_page(session):
        """GET 签到页面并提取 formhash Discuz 常见的 CSRF 字段"""
        response = session.get(
            "https://www.right.com.cn/forum/forum.php",
            headers={"Accept": EnShan._HTML_ACCEPT},
            timeout=15,
        )
        response.raise_for_status()
        html = response.text
        # 常见两种位置：隐藏 input name="formhash" value="..." 或 js var formhash = '...'
        m = re.search(r'name=["\']formhash["\']\s+value=["\']([0-9a-fA-F]+)["\']', html)
        if not m:
            m = re.search(r"formhash\s*[:=]\s*['\"]([0-9a-fA-F]+)['\"]", html)
        if not m:
            # 有时 formhash 包含非十六进制字符，放宽匹配
            m = re.search(r'name=["\']formhash["\']\s+value=["\']([^"\']+)["\']', html)

        if not m:
            raise RuntimeError("无法在页面中找到 formhash，请检查页面或手动查看 HTML")
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
            # print(f'status_code: {response.status_code}, text: {response.text[:2000]}')
        return msg

    @staticmethod
    def get_info(session):
        msg = []
        try:
            # 请求放入 try 块，避免 521 等非 200 状态码中断签到流程
            response = session.get(
                "https://www.right.com.cn/forum/home.php?mod=spacecp&ac=credit&showcredit=1",
                headers={"Accept": EnShan._HTML_ACCEPT},
                timeout=15,
            )
            html = response.text
            coin_match = re.findall("恩山币: </em>(.*?)&nbsp;", html)
            point_match = re.findall("<em>积分: </em>(.*?)<span", html)
            if coin_match and point_match:
                msg = [
                    {
                        "name": "恩山币",
                        "value": coin_match[0],
                    },
                    {
                        "name": "积分",
                        "value": point_match[0],
                    },
                ]
            else:
                msg = [
                    {
                        "name": "资产信息",
                        "value": f"获取失败(HTTP {response.status_code}，可能被 WAF 拦截)",
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
                "Referer": "https://www.right.com.cn/forum/",
                "Cookie": cookie,
            }
        )
        try:
            form_hash = self.get_formhash_from_page(session=session)
        except Exception as e:
            return f"恩山签到失败：获取 formhash 异常: {e}"
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
