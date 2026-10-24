"""通用 Discuz 论坛 discuz 离线回归测试。

对应 Sitoi/dailycheckin#576(自定义站点签到)#556(自定义论坛签到)#549(3Y 论坛):
覆盖 Discuz 签到插件两大形态——
  1. 冒号插件 POST 形态(默认 dsu_paulsign:sign, 与 enshan 的 erling_qd 同族)
  2. 单段插件 GET 链接形态(zqlj_sign, #576 的 tekqart 真实示例, 与 fnnasclub 同族)

全部 HTTP 请求经 responses mock。无真实凭据、无网络访问。
"""

import pytest
import responses

from dailycheckin.discuz.main import Discuz

BASE = "https://bbs.example.com"
PLUGIN_PAGE_URL = f"{BASE}/plugin.php?id=dsu_paulsign:sign"
SIGN_POST_URL = f"{BASE}/plugin.php?id=dsu_paulsign:sign&operation=qiandao&infloat=1&inajax=1"

# #576 例一的真实站点与插件形态(公开 URL, 仅作 fixture 结构参照)
TEKQART = "https://www.tekqart.com"
TEKQART_PAGE_URL = f"{TEKQART}/plugin.php?id=zqlj_sign"
TEKQART_SIGN_URL = f"{TEKQART}/plugin.php?id=zqlj_sign&sign=f9578486"

PLUGIN_PAGE_HTML = '<html><input type="hidden" name="formhash" value="ab12cd" /><form>签到</form></html>'

# Discuz inajax 响应: Message 文案在 CDATA 内
SIGN_OK_AJAX = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<root><![CDATA[<div class="c"><strong>恭喜, 签到成功！</strong>奖励 2 个积分</div>]]></root>'
)
SIGN_ALREADY_AJAX = (
    '<?xml version="1.0" encoding="utf-8"?>\n<root><![CDATA[<div class="c">您今日已经签到, 请明天再来！</div>]]></root>'
)

# 整页 Message(#messagetext 提示框)与 zqlj_sign 常见文案(参照 fnnasclub)
TEKQART_PAGE_HTML = '<html><a href="plugin.php?id=zqlj_sign&sign=f9578486" class="btna">点击打卡</a></html>'
SIGN_OK_PAGE = '<html><div id="messagetext"><p>恭喜您, 打卡成功！</p></div></html>'
SIGN_ALREADY_PAGE = '<html><div id="messagetext"><p>您今天已经打过卡了, 请勿重复操作！</p></div></html>'


@pytest.fixture
def rsps():
    with responses.RequestsMock() as mock:
        yield mock


def _body(request):
    return request.body.decode() if isinstance(request.body, bytes) else request.body


class TestPostMode:
    """默认 sign_plugin=dsu_paulsign:sign 的 POST 形态。"""

    def test_success_flow_posts_formhash_and_reports_message(self, rsps):
        """正常流程: GET 插件页提取 formhash, POST 签到并透出 CDATA Message 文案。"""
        rsps.add(responses.GET, PLUGIN_PAGE_URL, body=PLUGIN_PAGE_HTML)
        rsps.add(responses.POST, SIGN_POST_URL, body=SIGN_OK_AJAX)

        msg = Discuz(check_item={"url": BASE, "cookie": "abc_auth=tokenA; abc_saltkey=keyB"}).main()

        assert "恭喜, 签到成功" in msg
        assert "奖励 2 个积分" in msg
        assert "bbs.example.com" in msg
        sign_req = rsps.calls[1].request
        assert "formhash=ab12cd" in _body(sign_req)
        assert "operation=qiandao" in sign_req.url
        # 请求头纪律(与 enshan PR 572 一致): 签到 POST 带 X-Requested-With, Cookie 经 jar 传递
        assert sign_req.headers["X-Requested-With"] == "XMLHttpRequest"
        assert "abc_auth=tokenA" in sign_req.headers["Cookie"]

    def test_already_signed_message(self, rsps):
        """已签到: 返回 Message 含「已经签到」时汇报今日已签到。"""
        rsps.add(responses.GET, PLUGIN_PAGE_URL, body=PLUGIN_PAGE_HTML)
        rsps.add(responses.POST, SIGN_POST_URL, body=SIGN_ALREADY_AJAX)

        msg = Discuz(check_item={"url": BASE, "cookie": "abc_auth=tokenA"}).main()

        assert "今日已签到" in msg

    def test_missing_formhash_returns_clear_failure(self, rsps):
        """formhash 缺失(登录墙/风控页/改版)时返回明确失败文案, 不抛裸异常。"""
        rsps.add(responses.GET, PLUGIN_PAGE_URL, body="<html>please login</html>")

        msg = Discuz(check_item={"url": BASE, "cookie": "abc_auth=tokenA"}).main()

        assert "签到失败" in msg
        assert "formhash" in msg
        assert len(rsps.calls) == 1

    def test_non_200_returns_status_in_failure(self, rsps):
        """非 200: 明确失败并包含状态码。"""
        rsps.add(responses.GET, PLUGIN_PAGE_URL, status=503, body="")

        msg = Discuz(check_item={"url": BASE, "cookie": "abc_auth=tokenA"}).main()

        assert "签到失败" in msg
        assert "503" in msg

    def test_submit_without_message_reports_inconclusive(self, rsps):
        """返回页无 Discuz Message: 汇报「已提交但未能确认结果」, 不伪造成功。"""
        rsps.add(responses.GET, PLUGIN_PAGE_URL, body=PLUGIN_PAGE_HTML)
        rsps.add(responses.POST, SIGN_POST_URL, body="<html>plain page</html>")

        msg = Discuz(check_item={"url": BASE, "cookie": "abc_auth=tokenA"}).main()

        assert "已提交但未能确认结果" in msg

    def test_missing_url_or_cookie_config_fails_without_request(self, rsps):
        msg = Discuz(check_item={"cookie": "a=b"}).main()
        assert "签到失败" in msg and "url" in msg

        msg2 = Discuz(check_item={"url": BASE}).main()
        assert "签到失败" in msg2 and "cookie" in msg2

        msg3 = Discuz(check_item={"url": "bbs.example.com", "cookie": "a=b"}).main()
        assert "签到失败" in msg3 and "url" in msg3
        assert len(rsps.calls) == 0


class TestGetMode:
    """sign_plugin 不含冒号的 GET 链接形态(#576 tekqart 例, zqlj_sign 插件)。"""

    def test_get_link_flow_with_tekqart_example(self, rsps):
        """GET 形态: 插件页取 sign 链接 token 后 GET 签到, 解析整页 Message。"""
        rsps.add(responses.GET, TEKQART_PAGE_URL, body=TEKQART_PAGE_HTML)
        rsps.add(responses.GET, TEKQART_SIGN_URL, body=SIGN_OK_PAGE)

        msg = Discuz(check_item={"url": TEKQART, "cookie": "qwe_auth=tokenA", "sign_plugin": "zqlj_sign"}).main()

        assert "打卡成功" in msg
        assert "www.tekqart.com" in msg
        sign_req = rsps.calls[1].request
        assert sign_req.url == TEKQART_SIGN_URL
        assert "qwe_auth=tokenA" in sign_req.headers["Cookie"]

    def test_already_signed_via_sign_link_response(self, rsps):
        """GET 形态已签到: 签到链接返回「已经打过卡/请勿重复」。"""
        rsps.add(responses.GET, TEKQART_PAGE_URL, body=TEKQART_PAGE_HTML)
        rsps.add(responses.GET, TEKQART_SIGN_URL, body=SIGN_ALREADY_PAGE)

        msg = Discuz(check_item={"url": TEKQART, "cookie": "qwe_auth=tokenA", "sign_plugin": "zqlj_sign"}).main()

        assert "今日已签到" in msg

    def test_page_without_sign_link_but_already_marked(self, rsps):
        """插件页无签到链接但含已签到标记: 直接汇报今日已签到, 不发第二个请求。"""
        page = '<html><a class="btna">今日已打卡</a></html>'
        rsps.add(responses.GET, TEKQART_PAGE_URL, body=page)

        msg = Discuz(check_item={"url": TEKQART, "cookie": "qwe_auth=tokenA", "sign_plugin": "zqlj_sign"}).main()

        assert "今日已签到" in msg
        assert len(rsps.calls) == 1

    def test_page_without_sign_link_returns_clear_failure(self, rsps):
        """插件页既无签到链接也无已签到标记: 明确失败。"""
        rsps.add(responses.GET, TEKQART_PAGE_URL, body="<html>other page</html>")

        msg = Discuz(check_item={"url": TEKQART, "cookie": "qwe_auth=tokenA", "sign_plugin": "zqlj_sign"}).main()

        assert "签到失败" in msg
        assert "签到链接" in msg


def test_cookie_domain_uses_hostname_without_port():
    # 带端口 URL：cookie domain 必须是 hostname（不含端口），否则 cookie 永不随请求发送（A09 L-2）
    import inspect

    import dailycheckin.discuz.main as dm

    src = inspect.getsource(dm)
    assert "urlparse(url).hostname" in src, "cookie domain 应使用 hostname（不含端口）"
    assert "domain=host" in src
