"""吾爱破解论坛签到，参考 Elykia093/QLscript/scripts/pojie52.py。"""
import html
import re

import requests

from dailycheckin import CheckIn


class Pojie52(CheckIn):
    name = "吾爱破解"
    base = "https://www.52pojie.cn"
    sign_page = base + "/plugin.php?id=dsu_paulsign:sign"
    sign_post = sign_page + "&operation=qiandao&infloat=1&inajax=1"
    credit_page = base + "/home.php?mod=spacecp&ac=credit&showcredit=1"
    timeout = 15
    already_signed = ("您今天已经签到过了", "今日已签")

    def __init__(self, check_item):
        self.check_item = check_item
        self.outcome = "success"

    @staticmethod
    def extract_formhash(page):
        patterns = (
            r'name=["\']formhash["\']\s+value=["\']([^"\']+)',
            r"formhash=([a-zA-Z0-9]+)",
            r"['\"]formhash['\"]\s*:\s*['\"]([^'\"]+)",
        )
        for pattern in patterns:
            match = re.search(pattern, page)
            if match:
                return match.group(1)
        raise RuntimeError("未找到 formhash，Cookie 可能失效或页面结构已变更")

    @staticmethod
    def extract_credit(page):
        items = re.findall(r"<em>([^<:：]+)[:：]\s*</em>\s*([^<\s]+)", page)
        wanted = [(name, value) for name, value in items if any(
            keyword in name for keyword in ("吾爱币", "积分", "热心值", "技术成就")
        )]
        selected = wanted or items
        return "，".join(f"{name.strip()} {html.unescape(value.strip())}" for name, value in selected[:4]) or "未获取到积分信息"

    def main(self):
        cookie = self.check_item.get("cookie", "")
        if not cookie:
            raise ValueError("请配置吾爱破解 Cookie")
        with requests.Session() as session:
            session.headers.update({
                "Cookie": cookie,
                "Referer": self.base,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            })
            page = session.get(self.sign_page, timeout=self.timeout)
            page.raise_for_status()
            if any(word in page.text for word in self.already_signed):
                status = "今日已签到"
            else:
                payload = {"formhash": self.extract_formhash(page.text), "qdxq": "kx", "qdmode": "1", "todaysay": "每日签到", "fastreply": "0"}
                response = session.post(self.sign_post, data=payload, timeout=self.timeout)
                response.raise_for_status()
                if not any(word in response.text for word in ("签到成功", *self.already_signed)):
                    raise RuntimeError("签到失败：论坛未返回成功信息，请检查 Cookie 或论坛页面")
                status = "今日已签到" if any(word in response.text for word in self.already_signed) else "签到成功"
            try:
                credit = session.get(self.credit_page, timeout=self.timeout)
                credit.raise_for_status()
                info = self.extract_credit(credit.text)
            except requests.RequestException:
                info = "积分查询失败"
            if info in ("积分查询失败", "未获取到积分信息"):
                self.outcome = "partial"
            message = f"{status}，{info}"
            print(message)
            return message
