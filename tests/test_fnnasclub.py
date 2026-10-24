# fnnasclub 离线回归测试。
#
# Refs: Sitoi/dailycheckin#589
# - 无凭据公开页取证（2026-10-24）：plugin.php?id=zqlj_sign 返回 200 且仍含
#   <a href="plugin.php?id=zqlj_sign&sign=..." class="btna">点击打卡</a>，页面未改版；
#   「我的打卡动态」块仅登录态出现。据此用户侧取参失败应为登录墙/滑块页。
# - 登录墙识别：页面无打卡按钮且含登录/人机验证标志 → 输出可行动文案而非泛化取参失败。

import dailycheckin.fnnasclub.main as fnnas_module
from dailycheckin.fnnasclub.main import FnNasClub

SIGN_PAGE = """
<html><body>
<a href="plugin.php?id=zqlj_sign&sign=9f8e7d6c" class="btna">点击打卡</a>
<strong>我的打卡动态</strong>
<div class="bm_c"><ul><li>累计打卡：3 天</li><li>连续打卡：2 天</li></ul></div>
</body></html>
"""

SIGNED_PAGE = """
<html><body>
<a href="plugin.php?id=zqlj_sign&sign=9f8e7d6c" class="btna">今日已打卡</a>
<strong>我的打卡动态</strong>
<div class="bm_c"><ul><li>累计打卡：3 天</li></ul></div>
</body></html>
"""

LOGIN_WALL_PAGE = """
<html><body><title>登录 - 飞牛私有云论坛</title>
<form action="member.php?mod=logging&amp;action=login&amp;loginsubmit=yes" method="post">
<button type="submit">登录</button></form>
</body></html>
"""

CAPTCHA_WALL_PAGE = """
<html><body><div class="captcha">请拖动滑块完成人机验证</div></body></html>
"""

RESTRUCTURED_PAGE = """
<html><body><div>某种未来未知的新版页面结构</div></body></html>
"""

SIGN_SUCCESS_PAGE = "<html><body>恭喜您，打卡成功！</body></html>"
SIGN_DUP_PAGE = "<html><body>您今天已经打过卡了，请勿重复操作！</body></html>"


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, plugin_page, sign_result_page=None):
        self.plugin_page = plugin_page
        self.sign_result_page = sign_result_page
        self.calls = []
        self.headers = {}

    def get(self, url, timeout=None):
        self.calls.append(url)
        if "sign=" in url and "zqlj_sign&sign=" in url:
            return FakeResponse(self.sign_result_page or SIGN_SUCCESS_PAGE)
        return FakeResponse(self.plugin_page)


def _run_main(session):
    real_requests = fnnas_module.requests

    class _FakeRequests:
        Session = staticmethod(lambda: session)

    fnnas_module.requests = _FakeRequests
    try:
        return FnNasClub(check_item={"cookie": "placeholder"}).main()
    finally:
        fnnas_module.requests = real_requests


def test_is_login_wall_detection():
    assert FnNasClub._is_login_wall(LOGIN_WALL_PAGE) is True
    assert FnNasClub._is_login_wall(CAPTCHA_WALL_PAGE) is True
    # 有打卡按钮的页面（无论未签/已签）与无标志的未知页面都不算登录墙
    assert FnNasClub._is_login_wall(SIGN_PAGE) is False
    assert FnNasClub._is_login_wall(SIGNED_PAGE) is False
    assert FnNasClub._is_login_wall(RESTRUCTURED_PAGE) is False


def test_main_login_wall_outputs_actionable_message():
    # #589: 登录墙 → 「疑似 Cookie 失效或触发人机验证」，而非泛化取参失败。
    session = FakeSession(LOGIN_WALL_PAGE)
    msg = _run_main(session)
    assert "疑似 Cookie 失效或触发人机验证" in msg
    assert "未能成功获取sign参数" not in msg
    # 命中登录墙后不再继续请求签到与动态页
    assert len(session.calls) == 1


def test_main_normal_sign_flow():
    session = FakeSession(SIGN_PAGE, sign_result_page=SIGN_SUCCESS_PAGE)
    msg = _run_main(session)
    assert "签到成功" in msg
    assert "累计打卡: 3 天" in msg


def test_main_already_signed_flow():
    session = FakeSession(SIGNED_PAGE, sign_result_page=SIGN_DUP_PAGE)
    msg = _run_main(session)
    assert "您已签到，请勿重复签到" in msg


def test_main_unknown_page_keeps_generic_message():
    # 页面改版（无按钮也无登录标志）→ 保持原有泛化文案，不误报登录墙。
    session = FakeSession(RESTRUCTURED_PAGE)
    msg = _run_main(session)
    assert "未能成功获取sign参数" in msg
    assert "疑似 Cookie 失效" not in msg
