"""恩山无线论坛 enshan 离线回归测试。

复现设计取自维护报告 A03 §3.2 (上游 issues #569/#542/#501/#548/#584)。
期望行为对应融合修复: Sitoi/dailycheckin#562 为基底 + #572 请求头纪律 + #557 防御结构。

全部 HTTP 请求经 responses mock。无真实凭据、无网络访问。
"""

import pytest
import responses

from dailycheckin.enshan.main import EnShan

FORUM_URL = "https://www.right.com.cn/forum/forum.php"
SIGN_URL = "https://www.right.com.cn/forum/plugin.php?id=erling_qd:action&action=sign"
CREDIT_URL = "https://www.right.com.cn/forum/home.php?mod=spacecp&ac=credit&showcredit=1"

# PR 562（W-Webber）方案中的浏览器 UA
UA_562 = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)

SIGN_PAGE_HTML = '<html><input type="hidden" name="formhash" value="ab12cd" /></html>'
CREDIT_PAGE_HTML = "<li>恩山币: </em>88&nbsp;</li><li><em>积分: </em>666<span>点</span></li>"


@pytest.fixture
def rsps():
    with responses.RequestsMock() as mock:
        yield mock


def _mock_sign_ok(mock, days=3):
    mock.add(
        responses.POST,
        SIGN_URL,
        json={"success": True, "message": "签到成功", "continuous_days": days},
    )


class TestWaf521:
    def test_formhash_page_521_returns_clear_failure_without_raise(self, rsps):
        """#569: WAF 521 时不得抛裸异常。须返回含状态码说明的失败信息。"""
        rsps.add(responses.GET, FORUM_URL, status=521, body="")

        msg = EnShan(check_item={"cookie": "htVD_2132_auth=token; htVD_2132_saltkey=key"}).main()

        assert "521" in msg
        assert "WAF" in msg
        assert "Cookie" in msg

    def test_credit_page_521_keeps_sign_result_and_reports_status(self, rsps):
        """#569/#501: 积分页 521 只降级积分展示。签到结果必须保留且带状态码说明。"""
        rsps.add(responses.GET, FORUM_URL, body=SIGN_PAGE_HTML)
        _mock_sign_ok(rsps, days=2)
        rsps.add(responses.GET, CREDIT_URL, status=521, body="")

        msg = EnShan(check_item={"cookie": "htVD_2132_auth=token"}).main()

        assert "签到成功" in msg
        assert "已连续签到2天" in msg
        assert "恩山返回 521" in msg


class TestSignFlow:
    def test_success_flow_extracts_formhash_and_posts_sign(self, rsps):
        """正常流程: 提取 formhash 后 POST 新签到流并解析积分页。"""
        rsps.add(responses.GET, FORUM_URL, body=SIGN_PAGE_HTML)
        _mock_sign_ok(rsps)
        rsps.add(responses.GET, CREDIT_URL, body=CREDIT_PAGE_HTML)

        msg = EnShan(check_item={"cookie": "htVD_2132_auth=tokenA; htVD_2132_saltkey=keyB"}).main()

        assert "签到成功" in msg
        assert "已连续签到3天" in msg
        assert "恩山币" in msg and "88" in msg
        assert "积分" in msg and "666" in msg

        forum_req, sign_req, credit_req = [call.request for call in rsps.calls]
        # 签到 POST 保持新签到流：带 formhash 表单
        sign_body = sign_req.body.decode() if isinstance(sign_req.body, bytes) else sign_req.body
        assert "formhash=ab12cd" in sign_body
        # 积分页走小写 /forum/ 路径（PR 562）
        assert credit_req.url.startswith("https://www.right.com.cn/forum/home.php")

    def test_request_header_discipline(self, rsps):
        """PR 572 请求头纪律 + 562 UA: 页面 GET 用 text/html Accept。POST 加 X-Requested-With。"""
        rsps.add(responses.GET, FORUM_URL, body=SIGN_PAGE_HTML)
        _mock_sign_ok(rsps)
        rsps.add(responses.GET, CREDIT_URL, body=CREDIT_PAGE_HTML)

        EnShan(check_item={"cookie": "htVD_2132_auth=tokenA"}).main()

        forum_req, sign_req, credit_req = [call.request for call in rsps.calls]
        for page_req in (forum_req, credit_req):
            assert page_req.headers["User-Agent"] == UA_562
            assert page_req.headers["Accept"].startswith("text/html")
        assert sign_req.headers["X-Requested-With"] == "XMLHttpRequest"

    def test_cookie_passed_via_cookie_jar_not_hardcoded_header(self, rsps):
        """PR 562: Cookie 经 cookie jar 传递 (WAF Set-Cookie 应答才能回写生效)。"""
        rsps.add(responses.GET, FORUM_URL, body=SIGN_PAGE_HTML)
        _mock_sign_ok(rsps)
        rsps.add(responses.GET, CREDIT_URL, body=CREDIT_PAGE_HTML)

        check = EnShan(check_item={"cookie": "htVD_2132_auth=tokenA; htVD_2132_saltkey=keyB"})
        check.main()
        # 通过第二次请求（签到 POST）验证请求头中的 Cookie 由 cookie jar 生成
        sign_cookie_header = rsps.calls[1].request.headers["Cookie"]
        assert "htVD_2132_auth=tokenA" in sign_cookie_header
        assert "htVD_2132_saltkey=keyB" in sign_cookie_header


class TestDefensiveStructure:
    def test_page_without_formhash_returns_clear_failure(self, rsps):
        """#501: 页面无 formhash (如返回登录页/质询页) 时返回明确失败文案。不抛裸异常。"""
        rsps.add(responses.GET, FORUM_URL, body="<html>please login</html>")

        msg = EnShan(check_item={"cookie": "htVD_2132_auth=token"}).main()

        assert "formhash" in msg
        assert "WAF" in msg or "Cookie" in msg

    def test_credit_page_without_match_degrades_not_crash(self, rsps):
        """#501: 积分页解析不到数据时降级为「获取积分失败」。不影响签到结果。"""
        rsps.add(responses.GET, FORUM_URL, body=SIGN_PAGE_HTML)
        _mock_sign_ok(rsps)
        rsps.add(responses.GET, CREDIT_URL, body="<html>some other page</html>")

        msg = EnShan(check_item={"cookie": "htVD_2132_auth=token"}).main()

        assert "签到成功" in msg
        assert "获取积分失败" in msg
