"""滴滴福利中心集成，参考 back-101/zyqinglong/ddcx.py。"""
import asyncio

from dailycheckin import CheckIn
from .client import DiDiWelfare


class Didi(CheckIn):
    name = "滴滴出行"

    def __init__(self, check_item):
        self.check_item = check_item
        self.outcome = "success"
        self.messages = []

    def main(self):
        token = self.check_item.get("token", "").strip()
        if not token:
            raise ValueError("请配置滴滴 token")
        alias = self.check_item.get("account_name", "").strip()
        raw_token = f"{alias}#{token}" if alias else token
        runner = DiDiWelfare(raw_token)
        self.messages = runner.messages
        asyncio.run(runner.run())
        if runner.token_dead:
            self.outcome = "failed"
        elif runner.err:
            self.outcome = "partial" if runner.ok else "failed"
        elif runner.warn:
            self.outcome = "partial"
        return "\n".join(runner.messages)
