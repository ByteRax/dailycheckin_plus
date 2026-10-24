import hashlib
import json
import os
import time

import requests
import urllib3

from dailycheckin import CheckIn

urllib3.disable_warnings()


class SMZDM(CheckIn):
    name = "什么值得买"

    def __init__(self, check_item: dict):
        self.check_item = check_item

    def robot_token(self, headers):
        ts = round(time.time() * 1000)
        url = "https://user-api.smzdm.com/robot/token"
        data = {
            "f": "android",
            "v": "10.4.1",
            "weixin": 1,
            "time": ts,
            "sign": hashlib.md5(
                bytes(
                    f"f=android&time={ts}&v=10.4.1&weixin=1&key=apr1$AwP!wRRT$gJ/q.X24poeBInlUJC",
                    encoding="utf-8",
                )
            )
            .hexdigest()
            .upper(),
        }
        html = requests.post(url=url, headers=headers, data=data, timeout=10)
        result = html.json()
        # Refs: Sitoi/dailycheckin#479 #571 已签到/风控场景返回 data:null，判空避免裸 TypeError
        token = (result.get("data") or {}).get("token")
        if not token:
            raise Exception(f"获取 robot_token 失败: {result.get('error_msg') or str(result)[:200]}")
        return token

    def sign(self, headers, token):
        time_stamp = round(time.time() * 1000)
        data = {
            "f": "android",
            "v": "10.4.1",
            "sk": "ierkM0OZZbsuBKLoAgQ6OJneLMXBQXmzX+LXkNTuKch8Ui2jGlahuFyWIzBiDq/L",
            "weixin": 1,
            "time": time_stamp,
            "token": token,
            "sign": hashlib.md5(
                bytes(
                    f"f=android&sk=ierkM0OZZbsuBKLoAgQ6OJneLMXBQXmzX+LXkNTuKch8Ui2jGlahuFyWIzBiDq/L&time={time_stamp}&token={token}&v=10.4.1&weixin=1&key=apr1$AwP!wRRT$gJ/q.X24poeBInlUJC",
                    encoding="utf-8",
                )
            )
            .hexdigest()
            .upper(),
        }
        url = "https://user-api.smzdm.com/checkin"
        resp = requests.post(url=url, headers=headers, data=data, timeout=10)
        result = resp.json()
        error_msg = result.get("error_msg")
        if error_msg is None:
            error_msg = f"签到响应异常: {str(result)[:200]}"
        return error_msg, data

    def all_reward(self, headers, data):
        url2 = "https://user-api.smzdm.com/checkin/all_reward"
        resp = requests.post(url=url2, headers=headers, data=data, timeout=10)
        result = resp.json()
        # Refs: Sitoi/dailycheckin#479 #571 三态防护：正常 / data:null（已签到）/ 结构缺失（解析降级）
        data_part = result.get("data")
        if not data_part:
            return [{"name": "签到奖励", "value": "今日已签到或无奖励信息"}]
        normal_reward = data_part.get("normal_reward") or {}
        reward_add = normal_reward.get("reward_add") or {}
        if reward_add.get("content") is not None:
            return [
                {
                    "name": "签到奖励",
                    "value": reward_add.get("content"),
                },
                {
                    "name": "连续签到",
                    "value": normal_reward.get("sub_title", ""),
                },
            ]
        error_code = result.get("error_code", "")
        return [{"name": "签到奖励", "value": f"签到奖励信息解析失败（响应结构异常，error_code: {error_code}）"}]

    def main(self):
        cookie = self.check_item.get("cookie")
        headers = {
            "Host": "user-api.smzdm.com",
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": cookie,
            "User-Agent": "smzdm_android_V10.4.1 rv:841 (22021211RC;Android12;zh)smzdmapp",
        }
        token = self.robot_token(headers)
        error_msg, data = self.sign(headers, token)
        msg = []
        msg.append({"name": "签到结果", "value": error_msg})
        reward_msg = self.all_reward(headers, data)
        msg += reward_msg
        msg = "\n".join([f"{one.get('name')}: {one.get('value')}" for one in msg])
        return msg


if __name__ == "__main__":
    with open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"),
        encoding="utf-8",
    ) as f:
        datas = json.loads(f.read())
    _check_item = datas.get("SMZDM", [])[0]
    print(SMZDM(check_item=_check_item).main())
