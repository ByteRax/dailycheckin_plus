import json
import os

import requests

from dailycheckin import CheckIn


class Quark(CheckIn):
    name = "夸克网盘"

    def __init__(self, check_item: dict):
        self.check_item = check_item
        self.cookie = check_item.get("cookie", "")
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

    def check_sign_status(self):
        state_url = "https://drive-m.quark.cn/1/clouddrive/capacity/growth/info?pr=ucpro&fr=pc&uc_param_str="
        headers = {"Cookie": self.cookie, "User-Agent": self.user_agent}
        try:
            state_response = requests.get(state_url, headers=headers, timeout=15)
            state_response.raise_for_status()
        except requests.RequestException as e:
            print(f"{self.name} 请求失败，请检查Cookie或网络连接是否正确。")
            print(e)
            return None
        response = state_response.json()
        sign = (response.get("data") or {}).get("cap_sign") or {}
        if sign.get("sign_daily"):
            # sign_daily_reward 单位为字节（与 QuarkAutoSignIn 一致）
            number = sign.get("sign_daily_reward", 0) / 1024 / 1024
            progress = (sign.get("sign_progress", 0) / sign.get("sign_target", 1)) * 100
            return [
                {
                    "name": "夸克网盘",
                    "value": f"今日已签到获取{number:.1f}MB，进度{progress:.0f}%",
                }
            ]
        return None

    def perform_sign(self):
        sign_url = "https://drive-m.quark.cn/1/clouddrive/capacity/growth/sign?pr=ucpro&fr=pc&uc_param_str="
        params = {"sign_cyclic": True}
        headers = {"Content-Type": "application/json", "Cookie": self.cookie, "User-Agent": self.user_agent}
        try:
            sign_response = requests.post(sign_url, headers=headers, json=params, timeout=15)
            sign_response.raise_for_status()
        except requests.RequestException as e:
            print(f"{self.name} 签到请求失败，请检查Cookie或网络连接是否正确。")
            print(e)
            return None
        data_response = sign_response.json()
        if data_response.get("code") not in (0, "0"):
            return [
                {
                    "name": "夸克网盘",
                    "value": f"签到失败: {data_response.get('message') or data_response}",
                }
            ]
        # sign_daily_reward 单位为字节（与 QuarkAutoSignIn 一致）
        mb = (data_response.get("data") or {}).get("sign_daily_reward", 0) / 1024 / 1024
        return [
            {
                "name": "夸克网盘",
                "value": f"签到成功,获取到{mb:.1f}MB!",
            }
        ]

    def main(self):
        if not self.cookie:
            return "夸克网盘: 配置缺少 cookie"
        status_msg = self.check_sign_status()
        if status_msg:
            return "\n".join([f"{one.get('name')}: {one.get('value')}" for one in status_msg])
        sign_reward_msg = self.perform_sign()
        if sign_reward_msg:
            return "\n".join([f"{one.get('name')}: {one.get('value')}" for one in sign_reward_msg])
        return "夸克网盘: 签到失败，请检查配置或网络连接"


if __name__ == "__main__":
    with open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"),
        encoding="utf-8",
    ) as f:
        datas = json.loads(f.read())
    _check_item = datas.get("QUARK", [])[0]
    print(Quark(check_item=_check_item).main())
