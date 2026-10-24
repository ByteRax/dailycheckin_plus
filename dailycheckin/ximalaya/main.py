import json
import os

import requests

from dailycheckin import CheckIn


class Ximalaya(CheckIn):
    name = "喜马拉雅"

    # 接口事实（Refs: Sitoi/dailycheckin#452，调查报告 A03 §2；参考实现
    # ClydeTime/Quantumult xmlySign.js 与 lzwme/ql-scripts ql_xmlySign.ts，仅取接口事实）：
    # POST https://hybrid.ximalaya.com/web-activity/signIn/v2/signIn?v=new
    # JSON body {"aid": 87}，Cookie 鉴权（抓自喜马拉雅 APP），ret == 0 为成功；
    # msg 可能在顶层或 data.msg；ret != 0 的具体文案无「已签到」类证据，原样透传。
    _SIGN_URL = "https://hybrid.ximalaya.com/web-activity/signIn/v2/signIn"
    # cookie 抓自 APP 请求，配套 APP 客户端 UA（lzwme 参考实现所用）
    _UA = "ting/9.2.24.3 CFNetwork/1494.0.7 Darwin/23.4.0"
    # 响应里连续签到天数/奖励字段名无公开抓包证据，按离线测试 fixture 约定候选键，
    # 命中即输出、缺失不报错
    _CONTINUOUS_DAYS_KEYS = ("continuousDays", "signInDays", "continuous_days")
    _REWARD_KEYS = ("awardName", "award", "reward")

    def __init__(self, check_item):
        self.check_item = check_item

    @staticmethod
    def _first_present(mapping, keys):
        for key in keys:
            value = mapping.get(key)
            if value is not None:
                return value
        return None

    @classmethod
    def _report(cls, response):
        if response.status_code in (401, 403):
            return f"签到失败: Cookie 已失效（HTTP {response.status_code}），请重新抓取 APP Cookie"
        try:
            data = response.json()
        except ValueError:
            return "签到失败: Cookie 已失效（返回非 JSON 内容，疑似登录页），请重新抓取 APP Cookie"
        if not isinstance(data, dict):
            return f"签到失败: 响应格式异常: {type(data).__name__}"
        payload = data.get("data") if isinstance(data.get("data"), dict) else {}
        msg = data.get("msg") or payload.get("msg")
        if data.get("ret") == 0:
            msg_list = [
                {"name": "签到结果", "value": f"签到成功: {msg}" if msg else "签到成功"},
            ]
            days = cls._first_present(payload, cls._CONTINUOUS_DAYS_KEYS)
            if days is not None:
                msg_list.append({"name": "连续签到", "value": f"{days} 天"})
            reward = cls._first_present(payload, cls._REWARD_KEYS)
            if reward is not None:
                msg_list.append({"name": "签到奖励", "value": str(reward)})
            return "\n".join([f"{one.get('name')}: {one.get('value')}" for one in msg_list])
        return f"签到失败: [{data.get('ret')}] {msg or '请重新抓取 Cookie'}"

    def main(self):
        cookie = (self.check_item.get("cookie") or "").strip()
        if not cookie:
            return "签到失败: 未配置 Cookie"
        try:
            response = requests.post(
                self._SIGN_URL,
                params={"v": "new"},
                json={"aid": 87},
                headers={
                    "Cookie": cookie,
                    "Content-Type": "application/json",
                    "User-Agent": self._UA,
                },
                timeout=10,
            )
        except requests.RequestException as e:
            return f"签到失败: 网络异常: {e}"
        return self._report(response)


if __name__ == "__main__":
    with open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"),
        encoding="utf-8",
    ) as f:
        datas = json.loads(f.read())
    _check_item = datas.get("XIMALAYA", [])[0]
    print(Ximalaya(check_item=_check_item).main())
