"""天翼云盘 cloud189 离线回归测试。

Refs: Sitoi/dailycheckin#481。旧模块 2021 年随架构迁移被删, 本模块按现代协议重写;
协议事实来自 MIT 许可的 wes-lin/cloud189-sdk 源码(CloudAuthClient.ts / CloudClient.ts /
signature.ts / util.ts, 2026-10 快照):

- POST open.e.189.cn/api/logbox/config/encryptConf.do -> {"result": 0, "data": {"pubKey", "pre"}}
- GET cloud.189.cn/api/portal/unifyLoginForPC.action -> HTML(正则取 captchaToken/lt/paramId/reqId)
- POST open.e.189.cn/api/logbox/oauth2/loginSubmit.do -> {"result", "msg", "toUrl"}, result != 0 即失败
- POST api.cloud.189.cn/getSessionForPC.action(redirectURL=toUrl)-> {"sessionKey", ...}
- GET cloud.189.cn/mkt/userSign.action?rand&clientType=TELEANDROID&version&model&sessionKey
  -> {"isSign", "netdiskBonus"}; 该端点走 sessionKey 参数鉴权, 无需 Signature 头

全部 HTTP 请求经 responses mock, 无真实凭据、无网络访问;
RSA 加密用固定 fixture 密钥对做加解密回环断言(PKCS1 v1.5 密文随机, 无法断言固定密文)。
"""

import re
from urllib.parse import parse_qs, urlparse

import pytest
import responses
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA

from dailycheckin.cloud189.main import Cloud189

# 固定 fixture RSA 密钥对(1024 位, 仅测试用; 对应 encryptConf.do 下发的 pubKey 形态:
# 无 PEM 头尾的 base64 DER SubjectPublicKeyInfo)
PUBLIC_KEY_B64 = "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC1POc+bbh+N/wclFtlHpayWVwKQaq4zNpDNIUWu9gBVHQEnSttfiRq8ytah1ue+6uRSnq/tpc8rkuF62Z2Ir8K5DU3djFpeSWNCJfOx4C9nAPS0pNEjxIKEZ71pzrUPYPgyT80AbZfAp5sav6lAFcKKtpLe7N2RiQmpP9pUnWGCwIDAQAB"
PRIVATE_KEY_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIICdQIBADANBgkqhkiG9w0BAQEFAASCAl8wggJbAgEAAoGBALU85z5tuH43/ByUW2UelrJZXApBqrjM2kM0hRa72AFUdASdK21+JGrzK1qHW577q5FKer+2lzyuS4XrZnYivwrkNTd2MWl5JY0Il87HgL2cA9LSk0SPEgoRnvWnOtQ9g+DJPzQBtl8Cnmxq/qUAVwoq2kt7s3ZGJCak/2lSdYYLAgMBAAECgYBrqpuhbaMdcHrYK5ZD8zEJEKbp/OrD0AaVyByMTdlbqOUnXItRB4/w7TbDGAho4Q+iR4G2ZG1iAhUhoJ+E7M1aVZBFSihZzyKAuf9RNvuBxTfqtxyn3yGOrjClzOKGOhhcgIzBfrdmPwOuDRYRet/e2tUgLAny2bQvmp54pW9q4QJBAOX/8z60wiBw9lxTUP5B5crqwsf4dDg08k3bIjFikEQkw/2n6esfkdC6/r9DZDRGyCe5K1aiNnU3PJIRVDFpg3ECQQDJudB3mXRD/1heI2waV3nh6Bv4EPXwWAIMPlAHGzqIyk6p50xuu6TMqsz2ifrcjxKhwSNLF5UFvSKuzlCmdGs7AkB0npjpvKGJ7X0dRymUIjmv7+Ufm/zh2wbZLzlhLQbVZobyAMf87h7zZT1yIWuXjiRC8ALnhIx0VrOhpKO6AjQhAkB22kDmRoaHDaouBObLemC4Zj4cYTnWOrQyLICQP020jKXeWwXgdDQ71iJe25rvWmia3yWBN8q4j+AgaDSCbjNDAkA3lm5U8ijWa694JbEAUsntgiXUAOMtctQXJOz51I1dAAW5Xf6Xk+IaYR1aPikPE0Wnh6EU3P2NJ3nyyf50J8Ed\n"
    "-----END RSA PRIVATE KEY-----"
)

USERNAME = "18912345678"
PASSWORD = "p@ssw0rd-测试"
ENCRYPT_PRE = "{NRP}"

ENCRYPT_CONF_URL = "https://open.e.189.cn/api/logbox/config/encryptConf.do"
LOGIN_FORM_URL = "https://cloud.189.cn/api/portal/unifyLoginForPC.action"
LOGIN_SUBMIT_URL = "https://open.e.189.cn/api/logbox/oauth2/loginSubmit.do"
SESSION_URL = "https://api.cloud.189.cn/getSessionForPC.action"
USER_SIGN_URL = re.compile(r"https://cloud\.189\.cn/mkt/userSign\.action.*")

LOGIN_FORM_HTML = """
<input type='hidden' name='captchaToken' value='8d30750b3368284234a14361ef6a21dam9vi7nay'>
<script type="text/javascript">
  var clientType = '10020', accountType = '02';
  var lt = "LT-41813c5f-2d75-46b9-a3b4-8e21d1a3e5f1";
  var paramId = "param_id_fixture";
  var reqId = "req_id_fixture";
  var _ux_version = "V4.1";
</script>
"""


def _decrypt(hex_ciphertext):
    key = RSA.import_key(PRIVATE_KEY_PEM)
    sentinel = b"<<DECRYPT-FAILED>>"
    plain = PKCS1_v1_5.new(key).decrypt(bytes.fromhex(hex_ciphertext), sentinel)
    assert plain != sentinel, "fixture 私钥解密失败, 密文不是本密钥对加密所得"
    return plain.decode("utf-8")


def _make_checkin():
    return Cloud189(check_item={"username": USERNAME, "password": PASSWORD})


def _mock_login_ok(mock):
    mock.add(
        responses.POST, ENCRYPT_CONF_URL, json={"result": 0, "data": {"pubKey": PUBLIC_KEY_B64, "pre": ENCRYPT_PRE}}
    )
    mock.add(responses.GET, LOGIN_FORM_URL, body=LOGIN_FORM_HTML)
    mock.add(
        responses.POST,
        LOGIN_SUBMIT_URL,
        json={
            "result": 0,
            "msg": "登录成功",
            "toUrl": "https://m.cloud.189.cn/zhuanti/2020/loginErrorPc/index.html?appId=8025431004&paras=fixture",
        },
    )
    mock.add(responses.POST, SESSION_URL, json={"sessionKey": "sk-fixture", "accessToken": "at", "refreshToken": "rt"})


def _login_submit_body(calls):
    bodies = [call.request.body for call in calls if LOGIN_SUBMIT_URL in str(call.request.url)]
    assert bodies, "未捕获 loginSubmit.do 请求"
    return {k: v[0] for k, v in parse_qs(bodies[-1]).items()}


def test_login_and_sign_success():
    """登录成功 + 签到成功: 密码经 RSA 加密传输, 返回文案含奖励且不泄露密码。"""
    with responses.RequestsMock() as mock:
        _mock_login_ok(mock)
        mock.add(responses.GET, USER_SIGN_URL, json={"isSign": False, "netdiskBonus": 52})
        msg = _make_checkin().main()
        # responses 上下文退出时会清空调用记录, 先快照
        calls = list(mock.calls)

    assert "签到成功" in msg
    assert "52M" in msg
    assert "189****78" in msg, "账号信息应脱敏展示"
    assert PASSWORD not in msg and USERNAME not in msg

    # loginSubmit 表单: userName/password 均为 pre 前缀 + hex 密文, 解密回环等于明文
    form = _login_submit_body(calls)
    assert form["userName"].startswith(ENCRYPT_PRE)
    assert form["password"].startswith(ENCRYPT_PRE)
    assert _decrypt(form["userName"][len(ENCRYPT_PRE) :]) == USERNAME
    assert _decrypt(form["password"][len(ENCRYPT_PRE) :]) == PASSWORD
    # 登录表单固定参数(cloud189-sdk #builLoginForm)
    assert form["appKey"] == "8025431004"
    assert form["accountType"] == "02"
    assert form["clientType"] == "1"
    assert form["captchaToken"] == "8d30750b3368284234a14361ef6a21dam9vi7nay"
    assert form["paramId"] == "param_id_fixture"

    # userSign 请求: sessionKey 参数鉴权 + TELEANDROID 客户端参数, 无 Signature 头
    sign_calls = [call for call in calls if "userSign.action" in call.request.url]
    assert sign_calls, "未捕获 userSign.action 请求"
    query = parse_qs(urlparse(sign_calls[-1].request.url).query)
    assert query["sessionKey"] == ["sk-fixture"]
    assert query["clientType"] == ["TELEANDROID"]
    assert "Signature" not in sign_calls[-1].request.headers

    # getSessionForPC: redirectURL 来自 loginSubmit.toUrl, 客户端后缀参数齐全
    session_calls = [call for call in calls if "getSessionForPC" in call.request.url]
    assert session_calls
    session_query = parse_qs(urlparse(session_calls[-1].request.url).query)
    assert session_query["redirectURL"] == [
        "https://m.cloud.189.cn/zhuanti/2020/loginErrorPc/index.html?appId=8025431004&paras=fixture"
    ]
    assert session_query["clientType"] == ["TELEPC"]
    assert session_query["appId"] == ["8025431004"]


def test_already_signed():
    """已签到: isSign=True 时提示已签到, 不报错。"""
    with responses.RequestsMock() as mock:
        _mock_login_ok(mock)
        mock.add(responses.GET, USER_SIGN_URL, json={"isSign": True, "netdiskBonus": 0})
        msg = _make_checkin().main()

    assert "已签到" in msg
    assert PASSWORD not in msg and USERNAME not in msg


def test_login_wrong_password():
    """登录失败: loginSubmit 返回 result != 0 + msg(cloud189-sdk error.ts 的失败形态)。"""
    with responses.RequestsMock() as mock:
        mock.add(
            responses.POST, ENCRYPT_CONF_URL, json={"result": 0, "data": {"pubKey": PUBLIC_KEY_B64, "pre": ENCRYPT_PRE}}
        )
        mock.add(responses.GET, LOGIN_FORM_URL, body=LOGIN_FORM_HTML)
        mock.add(responses.POST, LOGIN_SUBMIT_URL, json={"result": 18, "msg": "用户名或密码错误"})
        msg = _make_checkin().main()

    assert "登录失败" in msg
    assert "用户名或密码错误" in msg
    assert PASSWORD not in msg and USERNAME not in msg


def test_login_captcha_or_risk_control():
    """登录失败(验证码/风控迹象): 文案给出明确提示。"""
    with responses.RequestsMock() as mock:
        mock.add(
            responses.POST, ENCRYPT_CONF_URL, json={"result": 0, "data": {"pubKey": PUBLIC_KEY_B64, "pre": ENCRYPT_PRE}}
        )
        mock.add(responses.GET, LOGIN_FORM_URL, body=LOGIN_FORM_HTML)
        mock.add(responses.POST, LOGIN_SUBMIT_URL, json={"result": 11, "msg": "请输入验证码"})
        msg = _make_checkin().main()

    assert "登录失败" in msg
    assert "验证码" in msg
    assert "风控" in msg or "稍后再试" in msg


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (200, {"result": -1, "msg": "get encrypt data fail"}),
        (500, {"error": "boom"}),
    ],
)
def test_encrypt_conf_failure(status, payload):
    """公钥接口异常: result != 0 或 HTTP 非 200 → 明确失败文案, 不再发起后续请求。"""
    with responses.RequestsMock() as mock:
        mock.add(responses.POST, ENCRYPT_CONF_URL, json=payload, status=status)
        msg = _make_checkin().main()

    assert "公钥" in msg and "失败" in msg
    assert PASSWORD not in msg
    assert all("loginSubmit" not in call.request.url for call in mock.calls), "公钥失败后不应继续登录"
