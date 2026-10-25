import unittest

from dailycheckin.anyrouter.main import AnyRouter


class _Response:
    def __init__(self, text="", status_code=200, headers=None, data=None):
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}
        self._data = data

    def json(self):
        if self._data is None:
            raise ValueError("not json")
        return self._data


class _RawCookieSession:
    def __init__(self):
        self.cookie_headers = []
        self.methods = []

    def post(self, **kwargs):
        self.methods.append("post")
        cookie_header = kwargs["headers"].get("Cookie", "")
        self.cookie_headers.append(cookie_header)
        if "session=abc" in cookie_header and "acw_tc=fresh" in cookie_header:
            return _Response(
                status_code=200,
                headers={"x-oneapi-request-id": "req-1"},
                data={"success": True, "message": "ok"},
            )
        return _Response(status_code=401, headers={}, data={})


class AnyRouterTest(unittest.TestCase):
    def test_main_accepts_upstream_account_keys(self):
        router = AnyRouter({"cookies": {"session": "abc"}, "api_user": "12345"})
        router.sign = lambda session, user_id, **kwargs: [
            {"name": "cookie", "value": AnyRouter._parse_cookie(kwargs["cookie"]).get("session")},
            {"name": "user", "value": user_id},
        ]

        self.assertEqual(router.main(), "cookie: abc\nuser: 12345")

    def test_parse_cookie_accepts_copied_cookie_header(self):
        self.assertEqual(
            AnyRouter._parse_cookie("Cookie: session=abc; acw_tc=def"),
            {"session": "abc", "acw_tc": "def"},
        )

    def test_unauthorized_empty_json_reports_cookie_or_api_user_problem(self):
        response = _Response(status_code=401, headers={}, data={})

        success, detail = AnyRouter._parse_sign_result(response)

        self.assertFalse(success)
        self.assertEqual(detail, "登录态无效，请检查 cookie/cookies 与 user_id/api_user 是否匹配或已过期")

    def test_sign_uses_raw_cookie_header_like_curl(self):
        session = _RawCookieSession()

        msg = AnyRouter.sign(
            session,
            "12345",
            cookie="session=abc; acw_tc=fresh; cdn_sec_tc=fresh; acw_sc__v2=fresh;",
        )

        self.assertIn({"name": "签到结果", "value": "成功"}, msg)
        self.assertEqual(["post"], session.methods)
        self.assertIn("session=abc", session.cookie_headers[-1])
        self.assertIn("acw_tc=fresh", session.cookie_headers[-1])


if __name__ == "__main__":
    unittest.main()
