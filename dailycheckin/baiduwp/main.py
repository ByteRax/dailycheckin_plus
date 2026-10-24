import copy
import json
import os
import re
import time

import requests

from dailycheckin import CheckIn


class BaiduWP(CheckIn):
    name = "百度网盘"
    """
    百度网盘会员成长值签到和答题功能。
    传入cookie 自动完成签到、答题和会员信息查询。
    """

    def __init__(self, check_item: dict):
        self.check_item = check_item
        self.cookie = check_item.get("cookie") or ""
        self.cookie_values = self._parse_cookie(self.cookie)
        self.cookie_changed = False
        # 运行前的账号快照, 用于在 config.json 中按索引定位当前账号
        self._check_item_snapshot = copy.deepcopy(check_item)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.91 Mobile Safari/537.36",
                "Referer": "https://pan.baidu.com/wap/svip/growth/task",
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Connection": "keep-alive",
                "Accept-Encoding": "gzip, deflate",
                "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )
        # Cookie 经 session cookie jar 传递（PR 591）：服务器续期下发的
        # Set-Cookie 才能写回并在后续请求生效，而不是被硬编码 Cookie 头一直覆盖
        for name, value in self.cookie_values.items():
            self.session.cookies.set(name, value, domain=".baidu.com", path="/")

    @staticmethod
    def _parse_cookie(cookie_header: str) -> dict:
        result = {}
        for item in cookie_header.split(";"):
            name, separator, value = item.strip().partition("=")
            if separator and name:
                result[name] = value
        return result

    def _get(self, url: str):
        resp = self.session.get(url, timeout=10)
        cookie_changed = False
        now = time.time()

        # requests 对同名不同 domain/path 的 cookie 会同时保留，这里先归一
        # 再把服务器的续期/过期同步进本地 cookie 快照（PR 591）
        for updated_cookie in resp.cookies:
            for current_cookie in list(self.session.cookies):
                if current_cookie.name == updated_cookie.name:
                    self.session.cookies.clear(
                        domain=current_cookie.domain,
                        path=current_cookie.path,
                        name=current_cookie.name,
                    )

            expired = updated_cookie.expires is not None and updated_cookie.expires <= now
            if expired:
                if updated_cookie.name in self.cookie_values:
                    self.cookie_values.pop(updated_cookie.name)
                    cookie_changed = True
                continue

            self.session.cookies.set_cookie(updated_cookie)
            if self.cookie_values.get(updated_cookie.name) != updated_cookie.value:
                self.cookie_values[updated_cookie.name] = updated_cookie.value
                cookie_changed = True

        if cookie_changed:
            self.cookie = "; ".join(f"{name}={value}" for name, value in self.cookie_values.items())
            self.cookie_changed = True
        return resp

    @staticmethod
    def _find_config_path():
        # 与 dailycheckin/main.py 的配置查找顺序保持一致
        for one_path in [
            "/ql/scripts/config.json",
            "config.json",
            "../config.json",
            "./config/config.json",
            "../config/config.json",
            "/config.json",
        ]:
            path = os.path.join(os.getcwd(), one_path)
            if os.path.exists(path):
                return os.path.normpath(path)
        return None

    def _write_back_cookie(self):
        """把更新后的 cookie 原子写回 config.json 中的当前账号。其余账号与字段保持不变。"""
        config_path = self._find_config_path()
        if not config_path:
            return
        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print(f"写回 Cookie 失败: 读取 config.json 出错: {e}")
            return
        if not isinstance(data, dict):
            print("写回 Cookie 失败: config.json 结构异常, 跳过写回")
            return
        accounts = next(
            (value for key, value in data.items() if key.upper() == "BAIDUWP" and isinstance(value, list)),
            None,
        )
        if accounts is None:
            return
        # 按账号在配置列表中的索引匹配（对比运行前快照），匹配不到说明配置已被改动
        index = next((i for i, item in enumerate(accounts) if item == self._check_item_snapshot), None)
        if index is None:
            print("写回 Cookie 失败: config.json 中未匹配到当前账号（配置可能已被修改）, 跳过写回")
            return
        accounts[index]["cookie"] = self.cookie
        # 安全写入：临时文件 + os.replace 原子替换；失败保留原文件并打印警告
        temp_path = f"{config_path}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, config_path)
            print("已将更新后的 Cookie 写回 config.json")
        except Exception as e:
            print(f"写回 Cookie 失败: {e}")
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass

    def signin(self):
        url = "https://pan.baidu.com/rest/2.0/membership/level?app_id=250528&web=5&method=signin"
        resp = self._get(url)
        sign_point = None
        signin_error_msg = ""
        if resp.status_code == 200:
            m = re.search(r'points":(\d+)', resp.text)
            if m:
                sign_point = m.group(1)
            m2 = re.search(r'"error_msg":"(.*?)",', resp.text)
            if m2:
                signin_error_msg = m2.group(1)
        else:
            # 错误信息不得携带 Cookie 明文，避免凭据随通知渠道泄漏（PR 591 顺带修复）
            signin_error_msg = f"签到请求失败: {resp.status_code}（如持续失败请更新 Cookie）"
        return sign_point, signin_error_msg

    def get_question(self):
        url = "https://pan.baidu.com/act/v2/membergrowv2/getdailyquestion?app_id=250528&web=5"
        resp = self._get(url)
        answer = None
        ask_id = None
        if resp.status_code == 200:
            m = re.search(r'"answer":(\d+),', resp.text)
            if m:
                answer = m.group(1)
            m2 = re.search(r'"ask_id":(\d+),', resp.text)
            if m2:
                ask_id = m2.group(1)
        return ask_id, answer

    def answer_question(self, ask_id, answer):
        url = f"https://pan.baidu.com/act/v2/membergrowv2/answerquestion?app_id=250528&web=5&ask_id={ask_id}&answer={answer}"
        resp = self._get(url)
        answer_score = None
        answer_msg = ""
        if resp.status_code == 200:
            m = re.search(r'"score":(\d+)', resp.text)
            if m:
                answer_score = m.group(1)
            m2 = re.search(r'"show_msg":"(.*?)"', resp.text)
            if m2:
                answer_msg = m2.group(1)
        return answer_score, answer_msg

    def get_userinfo(self):
        url = "https://pan.baidu.com/rest/2.0/membership/user?app_id=250528&web=5&method=query"
        resp = self._get(url)
        current_value = None
        current_level = None
        if resp.status_code == 200:
            m = re.search(r'current_value":(\d+),', resp.text)
            if m:
                current_value = m.group(1)
            m2 = re.search(r'current_level":(\d+),', resp.text)
            if m2:
                current_level = m2.group(1)
        return current_level, current_value

    def main(self):
        sign_point, signin_error_msg = self.signin()
        time.sleep(3)
        ask_id, answer = self.get_question()
        answer_score, answer_msg = (None, "")
        if ask_id and answer:
            answer_score, answer_msg = self.answer_question(ask_id, answer)
        current_level, current_value = self.get_userinfo()
        # 仅在签到明确成功且 cookie 有更新时回写：先同步内存中的 check_item，
        # 再原子写回 config.json；写回失败只打印警告，不影响签到结果上报
        if sign_point is not None and not signin_error_msg and self.cookie_changed:
            self.check_item["cookie"] = self.cookie
            try:
                self._write_back_cookie()
            except Exception as e:
                print(f"写回 Cookie 失败: {e}")
        msg = f"签到获得{sign_point or ''}{signin_error_msg}\n答题获得{answer_score or ''}{answer_msg}\n当前会员等级{current_level or ''}，成长值{current_value or ''}"
        return msg


if __name__ == "__main__":
    with open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"),
        encoding="utf-8",
    ) as f:
        datas = json.loads(f.read())
    _check_item = datas.get("BAIDUWP", [])[0]
    print(BaiduWP(check_item=_check_item).main())
