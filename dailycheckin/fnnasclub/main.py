import json
import os
import re
import requests

from dailycheckin import CheckIn


class FnNasClub(CheckIn):
    name = "飞牛Nas论坛"

    # Refs: Sitoi/dailycheckin#589 登录墙/人机验证页特征：页面无打卡按钮时据此识别
    LOGIN_WALL_MARKERS = (
        "member.php?mod=logging",
        "action=login",
        "请登录",
        "请先登录",
        "登录后",
        "captcha",
        "滑块",
        "人机验证",
    )

    def __init__(self, check_item):
        self.check_item = check_item

    @classmethod
    def _is_login_wall(cls, html):
        """页面既无打卡按钮又带登录/人机验证标志时判定为登录墙或风控页。"""
        if re.search(r'plugin\.php\?id=zqlj_sign&sign=[0-9a-fA-F]+" class="btna"', html):
            return False
        return any(marker in html for marker in cls.LOGIN_WALL_MARKERS)

    @classmethod
    def get_sign_param_from_page(cls, session):
        """GET 签到页面并返回 (sign参数, 是否命中登录墙/人机验证页)"""
        response = session.get("https://club.fnnas.com/plugin.php?id=zqlj_sign", timeout=15)
        response.raise_for_status()
        try:
            html = response.text
            # 匹配签到按钮，抓取sign参数
            r_sign_btn = re.compile(r'<a href="plugin.php\?id=zqlj_sign&sign=([0-9a-fA-F]+)" class="btna">点击打卡</a>')
            r_signed_btn = re.compile(
                r'<a href="plugin.php\?id=zqlj_sign&sign=([0-9a-fA-F]+)" class="btna">今日已打卡</a>'
            )
            match = r_sign_btn.search(html)
            match_signed = r_signed_btn.search(html)
            sign_param = ""
            if match:
                # 匹配成功，取出sign参数
                sign_param = match.group(1)
            elif match_signed:
                # 匹配成功，取出sign参数
                sign_param = match_signed.group(1)

            if sign_param:
                return sign_param, False
            return "", cls._is_login_wall(html)
        except Exception as e:
            print(f"status_code: {response.status_code}, text: {response.text[:2000]}, exception: {e}")
        return None, False

    @staticmethod
    def sign(session, sign_param):
        if not sign_param:
            msg = [
                {
                    "name": "签到结果",
                    "value": "签到失败，未能成功获取sign参数",
                }
            ]
            return msg
        response = session.get(f"https://club.fnnas.com/plugin.php?id=zqlj_sign&sign={sign_param}", timeout=15)
        try:
            html = response.text
            # 匹配到 恭喜您，打卡成功！ 证明打卡成功
            if re.search(r"恭喜您，打卡成功！", html):
                msg = [
                    {
                        "name": "签到结果",
                        "value": "签到成功",
                    }
                ]
            elif re.search(r"您今天已经打过卡了，请勿重复操作！", html):
                msg = [
                    {
                        "name": "签到结果",
                        "value": "您已签到，请勿重复签到",
                    }
                ]
            else:
                msg = [
                    {
                        "name": "签到结果",
                        "value": "未知签到异常",
                    }
                ]
        except Exception as e:
            msg = [
                {
                    "name": "签到结果",
                    "value": f"签到异常，Exception: {e}, Status Code: {response.status_code}",
                }
            ]
            # print(f'status_code: {response.status_code}, text: {response.text[:2000]}')
        return msg

    @staticmethod
    def get_info(session):
        msg = []
        response = session.get("https://club.fnnas.com/plugin.php?id=zqlj_sign", timeout=15)
        response.raise_for_status()

        try:
            html = response.text
            # 1. 匹配“我的打卡动态”这一整块 HTML
            pattern = re.compile(
                r"<strong>\s*我的打卡动态\s*</strong>"  # strong 标题
                r".*?"  # 任意内容（非贪婪）
                r'<div[^>]*class="bm_c"[^>]*>.*?</div>',  # div.bm_c 完整区块
                re.S,
            )

            m = pattern.search(html)
            if not m:
                raise RuntimeError("没匹配到 “我的打卡动态” 这一段 HTML")

            block_html = m.group(0)

            # 2. 保证每个 <li> 独立一行
            block_html = re.sub(r"</li\s*>", "</li>\n", block_html)

            # 3. 去掉所有 HTML 标签
            text = re.sub(r"<[^>]+>", "", block_html)

            # 4. 这里直接把“我的打卡动态”整个从文本里删除
            text = text.replace("我的打卡动态", "")

            # 5. 按行切分并清理空白
            lines = [line.strip() for line in text.splitlines() if line.strip()]

            # 6. 分割冒号并生成 msg 列表
            for line in lines:
                # 兼容全角“：”和半角“:”
                if "：" in line:
                    sep = "："
                elif ":" in line:
                    sep = ":"
                else:
                    continue

                name, value = line.split(sep, 1)
                msg.append(
                    {
                        "name": name.strip(),
                        "value": value.strip(),
                    }
                )

        except Exception as e:
            msg = [
                {
                    "name": "获取打卡动态失败",
                    "value": str(e),
                }
            ]
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
        sign_param, login_wall = self.get_sign_param_from_page(session=session)
        if login_wall:
            # Refs: Sitoi/dailycheckin#589 无凭据取证（2026-10-24）公开页仍含打卡按钮、页面未改版，
            # 用户侧取参失败应为登录墙/滑块页，给出可行动文案而非泛化取参失败
            return "签到结果: 疑似 Cookie 失效或触发人机验证，请重新抓取 Cookie 后重试"
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
