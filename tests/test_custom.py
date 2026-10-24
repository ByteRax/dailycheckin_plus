"""通用自定义 HTTP 签到 custom 离线回归测试。

对应 Sitoi/dailycheckin#576 例二(gkinto.com WordPress 站, POST user.php 接口
action=user.checkin)及任意非 Discuz 形态的自定义签到请求。

全部 HTTP 请求经 responses mock。无真实凭据、无网络访问。
"""

import pytest
import requests
import responses

from dailycheckin.custom.main import Custom

# #576 例二的真实站点接口形态（公开 URL，仅作 fixture 结构参照）
GKINTO_URL = "https://www.gkinto.com/wp-content/themes/modown-child/action/user.php"
GKINTO_BODY = "action=user.checkin"
GKINTO_OK = '{"status":1,"msg":"签到成功","data":{"credit":2}}'
GKINTO_ALREADY = '{"status":0,"msg":"您今天已签到过了"}'

API_URL = "https://api.example.com/checkin"


@pytest.fixture
def rsps():
    with responses.RequestsMock() as mock:
        yield mock


def _body(request):
    return request.body.decode() if isinstance(request.body, bytes) else request.body


class TestSuccess:
    def test_get_2xx_without_regex_defaults_success(self, rsps):
        """GET + 2xx 且未配置 success: 默认按状态码判成功。"""
        rsps.add(responses.GET, API_URL, body="ok")

        msg = Custom(check_item={"url": API_URL, "cookie": "sid=abc"}).main()

        assert "签到成功" in msg
        request = rsps.calls[0].request
        assert request.headers["Cookie"] == "sid=abc"
        assert "Mozilla/5.0" in request.headers["User-Agent"]

    def test_post_json_body_with_success_regex(self, rsps):
        """POST + JSON body + success 正则命中才算成功。"""
        url = "https://api.example.com/user/checkin"
        rsps.add(responses.POST, url, body='{"code":0,"msg":"签到成功"}')

        msg = Custom(
            check_item={
                "url": url,
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": '{"action":"user.checkin"}',
                "success": "签到成功|success",
            }
        ).main()

        assert "签到成功" in msg
        request = rsps.calls[0].request
        assert _body(request) == '{"action":"user.checkin"}'
        assert request.headers["Content-Type"] == "application/json"

    def test_gkinto_wordpress_form_example(self, rsps):
        """#576 例二形态: WordPress modown 主题 user.php 表单接口。"""
        rsps.add(responses.POST, GKINTO_URL, body=GKINTO_OK)

        msg = Custom(
            check_item={
                "url": GKINTO_URL,
                "method": "POST",
                "headers": {"Content-Type": "application/x-www-form-urlencoded"},
                "body": GKINTO_BODY,
                "cookie": "wordpress_logged_in=user",
                "success": "签到成功",
            }
        ).main()

        assert "签到成功" in msg
        assert "www.gkinto.com" in msg
        request = rsps.calls[0].request
        assert _body(request) == GKINTO_BODY
        assert "wordpress_logged_in=user" in request.headers["Cookie"]


class TestAlready:
    def test_already_regex_priority_over_success(self, rsps):
        """already 与 success 同时命中时, already 优先报今日已签到。"""
        body = '{"msg":"您今天已签到，明天再来签到成功哦"}'
        rsps.add(responses.GET, API_URL, body=body)

        msg = Custom(check_item={"url": API_URL, "success": "签到成功", "already": "已签到"}).main()

        assert "今日已签到" in msg

    def test_already_match_without_success_config(self, rsps):
        """只配置 already: 命中即今日已签到(优先于 2xx 默认成功)。"""
        rsps.add(responses.GET, API_URL, body=GKINTO_ALREADY)

        msg = Custom(check_item={"url": API_URL, "already": "已签到"}).main()

        assert "今日已签到" in msg


class TestFailure:
    def test_non_2xx_without_regex_fails_with_status(self, rsps):
        """非 2xx 且未配置 success: 失败并附状态码。"""
        rsps.add(responses.GET, API_URL, status=503, body="server error")

        msg = Custom(check_item={"url": API_URL}).main()

        assert "签到失败" in msg
        assert "503" in msg

    def test_success_regex_configured_2xx_miss_fails(self, rsps):
        """误判防护: 配置了 success 就必须命中, 2xx 本身不再算成功。"""
        rsps.add(responses.GET, API_URL, body='{"code":403,"msg":"请先登录"}')

        msg = Custom(check_item={"url": API_URL, "success": "签到成功"}).main()

        assert "签到失败" in msg
        assert "请先登录" in msg

    def test_response_truncated_and_redacted(self, rsps):
        """失败时响应只取前 120 字符, 且 ≥20 位连续字母数字脱敏为 ***。"""
        token = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"  # 32 位
        body = f'{{"error":"token {token}","padding":"{"x" * 300}tail_marker"}}'
        rsps.add(responses.GET, API_URL, body=body)

        msg = Custom(check_item={"url": API_URL, "success": "never_match"}).main()

        assert "签到失败" in msg
        assert "***" in msg
        assert token not in msg  # 长 token 已脱敏
        assert "tail_marker" not in msg  # 超出 120 字符的部分被截断

    def test_short_tokens_not_redacted(self, rsps):
        """<20 位的普通字符串(如 code123456)不脱敏, 保留可读性。"""
        rsps.add(responses.GET, API_URL, body='{"code":"code123456","msg":"请先登录"}')

        msg = Custom(check_item={"url": API_URL, "success": "never_match"}).main()

        assert "code123456" in msg

    def test_missing_url_fails_without_request(self, rsps):
        msg = Custom(check_item={"cookie": "a=b"}).main()

        assert "签到失败" in msg
        assert "url" in msg
        assert len(rsps.calls) == 0


class TestConfigError:
    def test_bad_success_regex_reports_config_error(self, rsps):
        """success 正则语法错误: 报配置错误文案, 不抛异常, 不发请求。"""
        msg = Custom(check_item={"url": API_URL, "success": "["}).main()

        assert "签到失败" in msg
        assert "配置错误" in msg
        assert len(rsps.calls) == 0

    def test_bad_already_regex_reports_config_error(self, rsps):
        msg = Custom(check_item={"url": API_URL, "already": "(?P<"}).main()

        assert "签到失败" in msg
        assert "配置错误" in msg
        assert len(rsps.calls) == 0

    def test_unsupported_method_reports_config_error(self, rsps):
        """method 仅支持 GET/POST, 其他值报配置错误。"""
        msg = Custom(check_item={"url": API_URL, "method": "DELETE"}).main()

        assert "签到失败" in msg
        assert "配置错误" in msg
        assert len(rsps.calls) == 0


class TestRobustness:
    def test_network_exception_fails_cleanly(self, rsps):
        """网络异常: 明确失败, 不抛裸异常。"""
        rsps.add(responses.GET, API_URL, body=requests.ConnectionError("refused"))

        msg = Custom(check_item={"url": API_URL}).main()

        assert "签到失败" in msg
        assert "ConnectionError" in msg or "refused" in msg


class TestNaming:
    def test_default_task_name_is_url_host(self, rsps):
        rsps.add(responses.GET, API_URL, body="ok")

        msg = Custom(check_item={"url": API_URL}).main()

        assert "api.example.com" in msg

    def test_custom_task_name_displayed(self, rsps):
        rsps.add(responses.GET, API_URL, body="ok")

        msg = Custom(check_item={"url": API_URL, "name": "游戏论坛"}).main()

        assert "游戏论坛" in msg


def test_request_exception_shows_url_without_query():
    # 请求异常回显去掉 query（?token=… 不外泄）且不带异常原文（A09 L-5）
    obj = Custom(check_item={"url": "https://example.com/api?token=SECRET123", "success": "ok"})
    with responses.RequestsMock() as rs:
        rs.add(responses.GET, "https://example.com/api", body=requests.ConnectionError("connect error boom"))
        result = obj.main()
    assert "SECRET123" not in result
    assert "token" not in result
    assert "https://example.com/api" in result


def test_non_string_regex_reports_config_error():
    # already/success 非字符串（如 123）按配置错误处理, 不抛 TypeError 到编排器（A09 L-4b）
    obj = Custom(check_item={"url": "https://example.com/", "already": 123})
    result = obj.main()
    assert "配置错误" in result
