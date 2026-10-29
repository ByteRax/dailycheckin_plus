"""WPS 活动任务，移植自 Cat-zaizai/ZaiZaiCat-Checkin（MIT）。"""
from dailycheckin import CheckIn
from .daily_benefits import DailyBenefitsTasks
from .task_center import WPSTaskCenterPage
from .logging_utils import configure_logging


class WPS(CheckIn):
    name = "WPS"

    def __init__(self, check_item):
        self.check_item = check_item

    def main(self):
        self.outcome = "failed"
        configure_logging()
        account = dict(self.check_item)
        if not account.get("cookies") or not account.get("user_id"):
            raise ValueError("WPS 需要配置 user_id 和 cookies")
        results = []
        successes = []
        auth_expired = False
        subtask_failed = False
        for page in (WPSTaskCenterPage, DailyBenefitsTasks):
            runner = page(enable_notification=False, load_accounts=False)
            result = runner.process_account(account)
            successes.append(bool(result.get("success")))
            subtask_failed |= any(not item.get("success") for item in result.get("lottery_info", {}).get("results", []))
            results.extend(runner.build_notification_lines(result))
            if result.get("auth_expired") or any(
                text in str(result.get("message", ""))
                for text in ("Token已过期", "ErrNotLogin", "userNotLogin", "未登录", "请重新登录")
            ):
                auth_expired = True
                results.append("登录态失效，已停止后续任务")
                break
        if not auth_expired:
            self.outcome = "success" if all(successes) and not subtask_failed else "partial" if any(successes) else "failed"
        return "\n".join(results)
