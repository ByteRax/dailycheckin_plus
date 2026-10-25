import json
import os
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import requests

from dailycheckin import CheckIn


class _FnNasPageParser(HTMLParser):
    """Extract the small amount of state needed from the sign-in page."""

    def __init__(self):
        super().__init__()
        self.sign_param = ""
        self._anchor = None
        self._anchor_text = []
        self._heading_seen = False
        self._li_text = None
        self.info_lines = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self._anchor = attrs.get("href", "")
            self._anchor_text = []
        elif tag == "li" and self._heading_seen:
            self._li_text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor is not None:
            query = parse_qs(urlparse(self._anchor).query)
            sign = query.get("sign", [""])[0]
            text = "".join(self._anchor_text).strip()
            if query.get("id") == ["zqlj_sign"] and sign and text in {"点击打卡", "今日已打卡"}:
                self.sign_param = sign
            self._anchor = None
            self._anchor_text = []
        elif tag == "li" and self._li_text is not None:
            line = "".join(self._li_text).strip()
            if line:
                self.info_lines.append(line)
            self._li_text = None

    def handle_data(self, data):
        if "我的打卡动态" in data:
            self._heading_seen = True
        if self._anchor is not None:
            self._anchor_text.append(data)
        if self._li_text is not None:
            self._li_text.append(data)


class FnNasClub(CheckIn):
    name = "飞牛Nas论坛"

    def __init__(self, check_item):
        self.check_item = check_item

    @staticmethod
    def get_sign_param_from_page(session):
        """GET 签到页面并提取 sign"""
        response = session.get("https://club.fnnas.com/plugin.php?id=zqlj_sign", timeout=15)
        response.raise_for_status()
        tengine_error = response.headers.get("X-Tengine-Error")
        if tengine_error:
            raise RuntimeError("飞牛论坛返回了拦截页面，未获取到有效签到页面")

        parser = _FnNasPageParser()
        parser.feed(response.text)
        if not parser.sign_param:
            raise RuntimeError("未匹配到有效签到按钮或 sign 参数")
        return parser.sign_param

    @staticmethod
    def sign(session, sign_param):
        if not sign_param:
            raise RuntimeError("签到失败，未能成功获取 sign 参数")
        response = session.get(f"https://club.fnnas.com/plugin.php?id=zqlj_sign&sign={sign_param}", timeout=15)
        response.raise_for_status()
        html = response.text
        if "恭喜您，打卡成功！" in html:
            return [{"name": "签到结果", "value": "签到成功"}]
        if "您今天已经打过卡了，请勿重复操作！" in html:
            return [{"name": "签到结果", "value": "您已签到，请勿重复签到"}]
        raise RuntimeError("签到接口返回未知响应")

    @staticmethod
    def get_info(session):
        msg = []
        response = session.get("https://club.fnnas.com/plugin.php?id=zqlj_sign", timeout=15)
        response.raise_for_status()
        parser = _FnNasPageParser()
        parser.feed(response.text)
        if not parser._heading_seen:
            raise RuntimeError("没匹配到 “我的打卡动态” 这一段 HTML")
        for line in parser.info_lines:
            if "：" in line:
                sep = "："
            elif ":" in line:
                sep = ":"
            else:
                continue
            name, value = line.split(sep, 1)
            msg.append({"name": name.strip(), "value": value.strip()})
        return msg

    def main(self):
        cookie = self.check_item.get("cookie")
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Referer": "https://club.fnnas.com/portal.php",
                "Content-Type": "text/html; charset=utf-8",
                "Cookie": cookie,
            }
        )
        sign_param = self.get_sign_param_from_page(session=session)
        msg = self.sign(session=session, sign_param=sign_param)
        msg += self.get_info(session=session)
        msg = "\n".join([f"{one.get('name')}: {one.get('value')}" for one in msg])
        return msg


if __name__ == "__main__":
    with open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"),
        encoding="utf-8",
    ) as f:
        datas = json.loads(f.read())
    _check_item = datas.get("FNNASCLUB", [])[0]
    print(FnNasClub(check_item=_check_item).main())
