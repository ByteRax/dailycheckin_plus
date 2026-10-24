import base64
import builtins
import hashlib
import hmac
import json
import re
import smtplib
import ssl
import time
from email.header import Header
from email.mime.text import MIMEText
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

import requests


def _redact_urls(text: str) -> str:
    # requests 异常串会内嵌完整 URL（含 sendkey/bark key 路径段与编码后的推送内容）；
    # 覆盖两种形态：带 scheme 的完整 URL 与 requests 的 "url: /path" path-only 形态
    return re.sub(r"(?:https?://\S+|url: \S+)", "<url-redacted>", str(text))


def _serverchan_send(url, data):
    # Server 酱统一发送 + 成败判定：Turbo/Server酱³ 返回 body code==0（官方 SDK 一致，
    # 见 https://github.com/easychen/serverchan-sdk）；旧版 sc.ftqq.com 返回 errno==0。
    try:
        response = requests.post(url=url, data=data, timeout=10)
    except Exception as e:
        print(f"Server 酱推送失败！网络异常：{_redact_urls(e)}")
        return
    try:
        result = response.json()
    except Exception:
        print(f"Server 酱推送失败！HTTP {response.status_code} 响应解析失败")
        return
    if isinstance(result, dict):
        code = result["code"] if "code" in result else result.get("errno")
        detail = result.get("message") or result.get("errmsg")
    else:
        code, detail = None, result
    if code == 0 and not isinstance(code, bool):
        print("Server 酱推送成功！")
    else:
        print(f"Server 酱推送失败！{detail or result}")


def message2server(sckey, content):
    desp = content.replace("\n", "\n\n")
    if re.match(r"^sctp\d+t", sckey):
        # Server酱³ SendKey 误填进 SCKEY：与 SENDKEY 渠道同路由到 ft07 端点
        message2server_turbo(sendkey=sckey, content=content)
        return
    if sckey.startswith("SCT"):
        # Server酱·Turbo SendKey（SCT 前缀）误填进 SCKEY：走 sctapi.ftqq.com
        print("server 酱 Turbo 推送开始")
        _serverchan_send(url=f"https://sctapi.ftqq.com/{sckey}.send", data={"title": "每日签到", "desp": desp})
        return
    print("server 酱推送开始")
    _serverchan_send(url=f"https://sc.ftqq.com/{sckey}.send", data={"text": "每日签到", "desp": desp})


def message2server_turbo(sendkey, content):
    desp = content.replace("\n", "\n\n")
    if match := re.match(r"^sctp(\d+)t", sendkey):
        sc3uid = match.group(1)
        print("Server 酱³ 推送开始")
        # 官方路由同 easychen/serverchan-sdk：sctp<uid>t 前缀 → uid.push.ft07.com；
        # tags 为 SC³ 专用参数（官方 API 文档），随 form body 发送
        _serverchan_send(
            url=f"https://{sc3uid}.push.ft07.com/send/{sendkey}.send",
            data={"title": "每日签到", "desp": desp, "tags": "DailyCheckin"},
        )
    else:
        print("server 酱 Turbo 推送开始")
        _serverchan_send(url=f"https://sctapi.ftqq.com/{sendkey}.send", data={"title": "每日签到", "desp": desp})


def message2coolpush(
    coolpushskey,
    content,
    coolpushqq: bool = True,
    coolpushwx: bool = False,
    coolpushemail: bool = False,
):
    print("Cool Push 推送开始")
    params = {"c": content, "t": "每日签到"}
    if coolpushqq:
        requests.post(url=f"https://push.xuthus.cc/send/{coolpushskey}", params=params, timeout=10)
    if coolpushwx:
        requests.post(url=f"https://push.xuthus.cc/wx/{coolpushskey}", params=params, timeout=10)
    if coolpushemail:
        requests.post(url=f"https://push.xuthus.cc/email/{coolpushskey}", params=params, timeout=10)


def message2qmsg(qmsg_key, qmsg_type, content, qq=None, bot=None, qmsg_url=None):
    print("qmsg 酱推送开始")
    params = {"msg": content}
    if qq:
        params["qq"] = qq
    if bot:
        params["bot"] = bot
    base_url = (qmsg_url or "https://qmsg.zendee.cn").rstrip("/")
    if qmsg_type == "group":
        requests.get(url=f"{base_url}/group/{qmsg_key}", params=params, timeout=10)
    else:
        requests.get(url=f"{base_url}/send/{qmsg_key}", params=params, timeout=10)


def message2telegram(tg_api_host, tg_proxy, tg_bot_token, tg_user_id, content):
    print("Telegram 推送开始")
    send_data = {
        "chat_id": tg_user_id,
        "text": content,
        "disable_web_page_preview": "true",
    }
    if tg_api_host:
        url = f"https://{tg_api_host}/bot{tg_bot_token}/sendMessage"
    else:
        url = f"https://api.telegram.org/bot{tg_bot_token}/sendMessage"
    if tg_proxy:
        proxies = {
            "http": tg_proxy,
            "https": tg_proxy,
        }
    else:
        proxies = None
    requests.post(url=url, data=send_data, proxies=proxies, timeout=10)


def message2feishu(fskey, content):
    print("飞书 推送开始")
    data = {"msg_type": "text", "content": {"text": content}}
    requests.post(url=f"https://open.feishu.cn/open-apis/bot/v2/hook/{fskey}", json=data, timeout=10)


def message2dingtalk(dingtalk_secret, dingtalk_access_token, content):
    print("Dingtalk 推送开始")
    timestamp = str(round(time.time() * 1000))
    secret_enc = dingtalk_secret.encode("utf-8")
    string_to_sign = f"{timestamp}\n{dingtalk_secret}"
    string_to_sign_enc = string_to_sign.encode("utf-8")
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = quote_plus(base64.b64encode(hmac_code))
    send_data = {"msgtype": "text", "text": {"content": content}}
    requests.post(
        url=f"https://oapi.dingtalk.com/robot/send?access_token={dingtalk_access_token}&timestamp={timestamp}&sign={sign}",
        headers={"Content-Type": "application/json", "Charset": "UTF-8"},
        data=json.dumps(send_data),
        timeout=10,
    )


BARK_URL_MAX_LENGTH = 2000  # bark GET URL 过长会被服务端/网关拒绝：超限时按行切分分批发送


def _bark_build_url(bark_url, content, bark_group, bark_icon, bark_sound):
    parts = urlsplit(bark_url)
    path = parts.path if parts.path.endswith("/") else parts.path + "/"
    query = dict(parse_qsl(parts.query))
    if bark_group:
        query["group"] = bark_group
    if bark_icon:
        query["icon"] = bark_icon
    if bark_sound:
        query["sound"] = bark_sound
    return urlunsplit((parts.scheme, parts.netloc, path + quote_plus(content), urlencode(query), parts.fragment))


def _bark_split_chunks(bark_url, content, bark_group, bark_icon, bark_sound, limit=BARK_URL_MAX_LENGTH):
    def build(text):
        return _bark_build_url(bark_url, text, bark_group, bark_icon, bark_sound)

    if len(build("")) >= limit:
        # bark_url 本身已超限（如 query 过长），无从切分，维持单条发送
        return [content]
    chunks = []
    current = ""
    for line in content.splitlines():
        candidate = line if not current else f"{current}\n{line}"
        if current and len(build(candidate)) > limit:
            chunks.append(current)
            current = ""
            candidate = line
        # 单行自身超限时按可容纳的最大前缀硬切（二分），不丢字符
        while len(build(candidate)) > limit and len(candidate) > 1:
            lo, hi = 1, len(candidate) - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if len(build(candidate[:mid])) <= limit:
                    lo = mid
                else:
                    hi = mid - 1
            chunks.append(candidate[:lo])
            candidate = candidate[lo:]
        current = candidate
    if current:
        chunks.append(current)
    return chunks or [content]


def message2bark(bark_url: str, content, bark_group=None, bark_icon=None, bark_sound=None):
    print("Bark 推送开始")
    chunks = _bark_split_chunks(bark_url, content, bark_group, bark_icon, bark_sound)
    total = len(chunks)
    if total > 1:
        print(f"Bark 内容超长，拆分为 {total} 条推送")
    headers = {"Content-type": "application/x-www-form-urlencoded"}
    ok_count = 0
    for index, chunk in enumerate(chunks):
        if index:
            time.sleep(1)  # 分批连发易触发限流，间隔 1s
        try:
            response = requests.get(
                url=_bark_build_url(bark_url, chunk, bark_group, bark_icon, bark_sound),
                headers=headers,
                timeout=10,
            )
        except Exception as e:
            print(f"Bark 推送失败（{index + 1}/{total}）", _redact_urls(e))
            continue
        if 200 <= response.status_code < 300:
            ok_count += 1
            print(f"Bark 推送成功！（{index + 1}/{total}）")
        else:
            print(f"Bark 推送失败！HTTP {response.status_code}（{index + 1}/{total}）")
    if ok_count == 0:
        print("Bark 全部推送失败！")


def message2qywxrobot(qywx_key, content):
    print("企业微信群机器人推送开始")
    requests.post(
        url=f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={qywx_key}",
        data=json.dumps({"msgtype": "text", "text": {"content": content}}),
        timeout=10,
    )


def message2qywxapp(
    qywx_corpid,
    qywx_agentid,
    qywx_corpsecret,
    qywx_touser,
    qywx_media_id,
    qywx_origin,
    content,
):
    print("企业微信应用消息推送开始")
    base_url = "https://qyapi.weixin.qq.com"
    if qywx_origin:
        base_url = qywx_origin
    res = requests.get(f"{base_url}/cgi-bin/gettoken?corpid={qywx_corpid}&corpsecret={qywx_corpsecret}", timeout=10)
    token = res.json().get("access_token", False)
    if qywx_media_id:
        data = {
            "touser": qywx_touser,
            "msgtype": "mpnews",
            "agentid": int(qywx_agentid),
            "mpnews": {
                "articles": [
                    {
                        "title": "Dailycheckin 签到通知",
                        "thumb_media_id": qywx_media_id,
                        "author": "Sitoi",
                        "content_source_url": "https://github.com/Sitoi/dailycheckin",
                        "content": content.replace("\n", "<br>"),
                        "digest": content,
                    }
                ]
            },
        }
    else:
        data = {
            "touser": qywx_touser,
            "agentid": int(qywx_agentid),
            "msgtype": "textcard",
            "textcard": {
                "title": "Dailycheckin 签到通知",
                "description": content,
                "url": "https://github.com/Sitoi/dailycheckin",
                "btntxt": "开源项目",
            },
        }
    requests.post(
        url=f"{base_url}/cgi-bin/message/send?access_token={token}",
        data=json.dumps(data),
        timeout=10,
    )


def message2pushplus(pushplus_token, content, pushplus_topic=None):
    print("Pushplus 推送开始")
    data = {
        "token": pushplus_token,
        "title": "签到通知",
        "content": content.replace("\n", "<br>"),
        "template": "json",
    }
    if pushplus_topic:
        data["topic"] = pushplus_topic
    requests.post(url="http://www.pushplus.plus/send", data=json.dumps(data), timeout=10)


def message2wpush(wpush_apikey, content, wpush_channel=None, wpush_topic_code=None):
    print("WPUSH 推送开始")
    data = {
        "apikey": wpush_apikey,
        "title": "签到通知",
        "content": content,
        "channel": wpush_channel or "wechat",
    }
    if wpush_topic_code:
        data["topic_code"] = wpush_topic_code
    response = requests.post(
        url="https://api.wpush.cn/api/v1/send",
        json=data,
        headers={"Content-Type": "application/json"},
        timeout=10,
        allow_redirects=False,
    )
    try:
        result = response.json()
    except Exception:
        print("WPUSH 推送失败！响应解析失败")
        return
    # 成败只按响应 body 的 code 判定：WPUSH 鉴权失败时返回 HTTP 200 + body code 401，
    # 按 HTTP 状态码判定不可行（live 验证见 A02）。code 为布尔值时不得视为 0 成功。
    code = result.get("code")
    if code == 0 and not isinstance(code, bool):
        print("WPUSH 推送成功！")
    else:
        print(f"WPUSH 推送失败！错误信息：{result.get('message') or result}")


def message2gotify(gotify_url: str, gotify_token: str, gotify_priority: str, content: str) -> None:
    print("Gotify 服务启动")
    if not gotify_priority:
        gotify_priority = "3"
    url = f"{gotify_url}/message?token={gotify_token}"
    data = {
        "title": "Dailycheckin签到通知",
        "message": content,
        "priority": gotify_priority,
    }
    response = requests.post(url, data=data, timeout=10).json()

    if response.get("id"):
        print("Gotify 推送成功！")
    else:
        print("Gotify 推送失败！")


def message2ntfy(ntfy_url: str, ntfy_topic: str, ntfy_priority: str, content: str) -> None:
    def encode_rfc2047(text: str) -> str:
        """将文本编码为符合 RFC 2047 标准的格式"""
        encoded_bytes = base64.b64encode(text.encode("utf-8"))
        encoded_str = encoded_bytes.decode("utf-8")
        return f"=?utf-8?B?{encoded_str}?="

    print("Ntfy 服务启动")
    if not ntfy_url:
        ntfy_url = "https://ntfy.sh"
    if not ntfy_priority:
        ntfy_priority = "3"
    # 使用 RFC 2047 编码 title
    encoded_title = encode_rfc2047("Dailycheckin签到通知")

    data = content.encode(encoding="utf-8")
    headers = {"Title": encoded_title, "Priority": ntfy_priority}  # 使用编码后的 title
    url = f"{ntfy_url}/{ntfy_topic}"
    response = requests.post(url, data=data, headers=headers, timeout=10)
    if response.status_code == 200:  # 使用 response.status_code 进行检查
        print("Ntfy 推送成功！")
    else:
        print("Ntfy 推送失败！错误信息：", response.text)


def message2xxtui(xxtui_key, content):
    print("xxtui 推送开始")
    data = {"from": "DailyCheckIn 每日签到脚本", "title": "每日签到", "content": content}
    requests.post(url=f"https://www.xxtui.com/xxtui/{xxtui_key}", json=data, timeout=10)


def message2webhook(webhook_url: str, content: str, webhook_method=None, webhook_body=None) -> None:
    print("自定义 Webhook 推送开始")
    title = "签到通知"
    method = (webhook_method or "POST").upper()
    if method == "GET":
        response = requests.get(url=webhook_url, params={"title": title, "content": content}, timeout=10)
    else:
        template = webhook_body or '{"title":"{title}","content":"{content}"}'
        try:
            # 占位符按 JSON 字符串字面量转义后替换，content 含引号/换行时仍产出合法 JSON
            rendered = template.replace("{title}", json.dumps(title, ensure_ascii=False)[1:-1]).replace(
                "{content}", json.dumps(content, ensure_ascii=False)[1:-1]
            )
            body = json.loads(rendered)
        except Exception as e:
            print(f"自定义 Webhook 推送失败！webhook_body 模板解析失败：{e}")
            return
        response = requests.post(url=webhook_url, json=body, timeout=10)
    if 200 <= response.status_code < 300:
        print("自定义 Webhook 推送成功！")
    else:
        print(f"自定义 Webhook 推送失败！HTTP {response.status_code}")


def message2pushme(pushme_key: str, content: str) -> None:
    print("PushMe 推送开始")
    # title/content 由 requests params 机制负责 URL 编码
    response = requests.get(
        url=f"https://push.i-i.me/{pushme_key}",
        params={"title": "签到通知", "content": content},
        timeout=10,
    )
    if 200 <= response.status_code < 300:
        print("PushMe 推送成功！")
    else:
        print(f"PushMe 推送失败！HTTP {response.status_code}")


def message2qlapi(content: str) -> None:
    print("青龙 QLAPI 推送开始")
    qlapi = getattr(builtins, "QLAPI", None)
    if qlapi is None:
        print("未检测到青龙 QLAPI 环境，跳过")
        return
    qlapi.systemNotify({"title": "签到通知", "content": content})
    print("青龙 QLAPI 推送成功！")


def _smtp_use_ssl(smtp_ssl, port: int) -> bool:
    # 未配置 smtp_ssl 时按端口自动选：465 走 SSL，其余（587 等）走 STARTTLS；
    # 配置了 smtp_ssl 则以它为准（接受 bool 或 "true"/"false" 字符串）。
    if smtp_ssl is None or smtp_ssl == "":
        return port == 465
    if isinstance(smtp_ssl, bool):
        return smtp_ssl
    return str(smtp_ssl).strip().lower() in ("true", "1", "yes", "on")


def message2smtp(
    smtp_server: str,
    smtp_user: str,
    smtp_password: str,
    content: str,
    smtp_port=None,
    smtp_ssl=None,
    smtp_to=None,
) -> None:
    print("SMTP 邮件推送开始")
    try:
        port = int(smtp_port) if smtp_port else 465
    except (TypeError, ValueError):
        port = 465
    use_ssl = _smtp_use_ssl(smtp_ssl, port)
    recipients = [addr.strip() for addr in str(smtp_to or "").split(",") if addr.strip()] or [smtp_user]
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = Header("签到通知", "utf-8")
    msg["From"] = smtp_user
    msg["To"] = ", ".join(recipients)
    try:
        # 显式校验服务器证书：smtplib 缺省会话不验证证书，密码不能走不加密身份的隧道
        ctx = ssl.create_default_context()
        if use_ssl:
            client = smtplib.SMTP_SSL(smtp_server, port, timeout=10, context=ctx)
        else:
            client = smtplib.SMTP(smtp_server, port, timeout=10)
        with client:
            if not use_ssl:
                client.starttls(context=ctx)
            client.login(smtp_user, smtp_password)
            client.sendmail(smtp_user, recipients, msg.as_string())
        print("SMTP 邮件推送成功！")
    except Exception as e:
        print(f"SMTP 邮件推送失败！{e}")


def message2pushdeer(pushdeer_pushkey: str, content: str) -> None:
    print("PushDeer 推送开始")
    response = requests.post(
        url="https://api2.pushdeer.com/message/push",
        data={"pushkey": pushdeer_pushkey, "text": "签到通知", "desp": content},
        timeout=10,
    )
    try:
        result = response.json()
    except Exception:
        print(f"PushDeer 推送失败！HTTP {response.status_code} 响应解析失败")
        return
    # 成败按响应 body 的 code 判定：PushDeer 错误（如 9201）随 HTTP 200 返回
    code = result.get("code") if isinstance(result, dict) else None
    if code == 0 and not isinstance(code, bool):
        print("PushDeer 推送成功！")
    else:
        print(f"PushDeer 推送失败！{result.get('error') or result}")


def message2wxpusher(wxpusher_apptoken: str, wxpusher_uids, content: str) -> None:
    print("wxPusher 推送开始")
    if isinstance(wxpusher_uids, (list, tuple)):
        uids = [str(uid).strip() for uid in wxpusher_uids if str(uid).strip()]
    else:
        uids = [uid.strip() for uid in str(wxpusher_uids or "").split(",") if uid.strip()]
    response = requests.post(
        url="https://wxpusher.zjiecode.com/api/send/message",
        json={"appToken": wxpusher_apptoken, "content": content, "contentType": 1, "uids": uids},
        timeout=10,
    )
    try:
        result = response.json()
    except Exception:
        print("wxPusher 推送失败！响应解析失败")
        return
    # 成败按响应 body 的 code 判定：wxPusher 错误以 HTTP 200 + code!=0 返回
    code = result.get("code") if isinstance(result, dict) else None
    if code == 0 and not isinstance(code, bool):
        print("wxPusher 推送成功！")
    else:
        print(f"wxPusher 推送失败！错误信息：{result.get('msg') or result}")


def important_notice():
    # fork 版：重要通知改为读取本 fork 仓库带「通知」标签的开放 issue（原实现指向上游仓库）
    datas = requests.get(
        url="https://api.github.com/repos/ByteRax/dailycheckin_plus/issues?state=open&labels=通知",
        timeout=10,
    ).json()
    if datas:
        data = datas[0]
        title = data.get("title")
        body = data.get("body")
        url = data.get("html_url")
        notice = f"{title}\n{body}\n详细地址: {url}"
    else:
        notice = None
    return notice


def push_message(content_list: list, notice_info: dict):
    dingtalk_secret = notice_info.get("dingtalk_secret")
    dingtalk_access_token = notice_info.get("dingtalk_access_token")
    fskey = notice_info.get("fskey")
    bark_url = notice_info.get("bark_url")
    bark_group = notice_info.get("bark_group")
    bark_icon = notice_info.get("bark_icon")
    bark_sound = notice_info.get("bark_sound")
    sckey = notice_info.get("sckey")
    sendkey = notice_info.get("sendkey")
    qmsg_key = notice_info.get("qmsg_key")
    qmsg_type = notice_info.get("qmsg_type")
    qmsg_qq = notice_info.get("qmsg_qq")
    qmsg_bot = notice_info.get("qmsg_bot")
    qmsg_url = notice_info.get("qmsg_url")
    tg_bot_token = notice_info.get("tg_bot_token")
    tg_user_id = notice_info.get("tg_user_id")
    tg_api_host = notice_info.get("tg_api_host")
    tg_proxy = notice_info.get("tg_proxy")
    coolpushskey = notice_info.get("coolpushskey")
    coolpushqq = notice_info.get("coolpushqq")
    coolpushwx = notice_info.get("coolpushwx")
    coolpushemail = notice_info.get("coolpushemail")
    qywx_key = notice_info.get("qywx_key")
    qywx_corpid = notice_info.get("qywx_corpid")
    qywx_agentid = notice_info.get("qywx_agentid")
    qywx_corpsecret = notice_info.get("qywx_corpsecret")
    qywx_touser = notice_info.get("qywx_touser")
    qywx_media_id = notice_info.get("qywx_media_id")
    qywx_origin = notice_info.get("qywx_origin")
    pushplus_token = notice_info.get("pushplus_token")
    pushplus_topic = notice_info.get("pushplus_topic")
    wpush_apikey = notice_info.get("wpush_apikey")
    wpush_channel = notice_info.get("wpush_channel")
    wpush_topic_code = notice_info.get("wpush_topic_code")
    gotify_url = notice_info.get("gotify_url")
    gotify_token = notice_info.get("gotify_token")
    gotify_priority = notice_info.get("gotify_priority")
    ntfy_url = notice_info.get("ntfy_url")
    ntfy_topic = notice_info.get("ntfy_topic")
    ntfy_priority = notice_info.get("ntfy_priority")
    xxtui_key = notice_info.get("xxtui_key")
    webhook_url = notice_info.get("webhook_url")
    webhook_method = notice_info.get("webhook_method")
    webhook_body = notice_info.get("webhook_body")
    pushme_key = notice_info.get("pushme_key")
    qlapi = notice_info.get("qlapi")
    smtp_server = notice_info.get("smtp_server")
    smtp_port = notice_info.get("smtp_port")
    smtp_ssl = notice_info.get("smtp_ssl")
    smtp_user = notice_info.get("smtp_user")
    smtp_password = notice_info.get("smtp_password")
    smtp_to = notice_info.get("smtp_to")
    pushdeer_pushkey = notice_info.get("pushdeer_pushkey")
    wxpusher_apptoken = notice_info.get("wxpusher_apptoken")
    wxpusher_uids = notice_info.get("wxpusher_uids")
    content_str = "\n————————————\n\n".join(content_list)
    merge_push = notice_info.get("merge_push")
    # MERGE_PUSH 未配置时的默认规则：下方集合内的渠道（bark/qmsg/webhook 等 URL 长度或频率敏感型）
    # 默认「逐条拆分」发送；集合外渠道（Server酱/飞书/钉钉/TG/群机器人等）默认「合并为一条」。
    # Server酱（sckey/sendkey）因 Turbo 每日 5 条配额刻意留在集合外（默认合并）。
    # 用户始终可用 MERGE_PUSH: true/false 显式覆盖。
    message_list = [content_str]
    try:
        notice = important_notice()
        if notice:
            message_list.append(notice)
            content_list.append(notice)
    except Exception as e:
        print("获取重要通知失败:", e)
    if merge_push is None:
        if (
            qmsg_key
            or coolpushskey
            or qywx_touser
            or qywx_corpsecret
            or qywx_agentid
            or bark_url
            or pushplus_token
            or wpush_apikey
            or ntfy_topic
            or xxtui_key
            or webhook_url
            or pushme_key
            or qlapi
            or (smtp_server and smtp_user and smtp_password)
            or pushdeer_pushkey
            or wxpusher_apptoken
            or (gotify_url and gotify_token)
        ):
            merge_push = False
        else:
            merge_push = True
    if not merge_push:
        message_list = content_list
    for message in message_list:
        if qmsg_key:
            try:
                message2qmsg(
                    qmsg_key=qmsg_key,
                    qmsg_type=qmsg_type,
                    content=message,
                    qq=qmsg_qq,
                    bot=qmsg_bot,
                    qmsg_url=qmsg_url,
                )
            except Exception as e:
                print("qmsg 推送失败", e)
        if coolpushskey:
            try:
                message2coolpush(
                    coolpushskey=coolpushskey,
                    coolpushqq=coolpushqq,
                    coolpushwx=coolpushwx,
                    coolpushemail=coolpushemail,
                    content=message,
                )
            except Exception as e:
                print("coolpush 推送失败", e)
        if qywx_touser and qywx_corpid and qywx_corpsecret and qywx_agentid:
            try:
                message2qywxapp(
                    qywx_corpid=qywx_corpid,
                    qywx_agentid=qywx_agentid,
                    qywx_corpsecret=qywx_corpsecret,
                    qywx_touser=qywx_touser,
                    qywx_media_id=qywx_media_id,
                    qywx_origin=qywx_origin,
                    content=message,
                )
            except Exception as e:
                print("企业微信应用消息推送失败", e)
        if bark_url:
            try:
                message2bark(
                    bark_url=bark_url,
                    content=message,
                    bark_group=bark_group,
                    bark_icon=bark_icon,
                    bark_sound=bark_sound,
                )
            except Exception as e:
                print("Bark 推送失败", _redact_urls(e))
        if dingtalk_access_token and dingtalk_secret:
            try:
                message2dingtalk(
                    dingtalk_secret=dingtalk_secret,
                    dingtalk_access_token=dingtalk_access_token,
                    content=message,
                )
            except Exception as e:
                print("钉钉推送失败", e)
        if fskey:
            try:
                message2feishu(fskey=fskey, content=message)
            except Exception as e:
                print("飞书推送失败", e)
        if sckey:
            try:
                message2server(sckey=sckey, content=message)
            except Exception as e:
                print("Server 推送失败", e)
        if sendkey:
            try:
                message2server_turbo(sendkey=sendkey, content=message)
            except Exception as e:
                print("Server Turbo 推送失败", e)
        if qywx_key:
            try:
                message2qywxrobot(qywx_key=qywx_key, content=message)
            except Exception as e:
                print("企业微信群机器人推送失败", e)
        if pushplus_token:
            try:
                message2pushplus(
                    pushplus_token=pushplus_token,
                    content=message,
                    pushplus_topic=pushplus_topic,
                )
            except Exception as e:
                print("Pushplus 推送失败", e)
        if wpush_apikey:
            try:
                message2wpush(
                    wpush_apikey=wpush_apikey,
                    content=message,
                    wpush_channel=wpush_channel,
                    wpush_topic_code=wpush_topic_code,
                )
            except Exception as e:
                print("WPUSH 推送失败", e)
        if tg_user_id and tg_bot_token:
            try:
                message2telegram(
                    tg_api_host=tg_api_host,
                    tg_proxy=tg_proxy,
                    tg_user_id=tg_user_id,
                    tg_bot_token=tg_bot_token,
                    content=message,
                )
            except Exception as e:
                print("Telegram 推送失败", e)
        if gotify_url and gotify_token:
            try:
                message2gotify(
                    gotify_url=gotify_url,
                    gotify_token=gotify_token,
                    gotify_priority=gotify_priority,
                    content=message,
                )
            except Exception as e:
                print("Gotify 推送失败", e)
        if ntfy_topic:
            try:
                message2ntfy(
                    ntfy_url=ntfy_url,
                    ntfy_topic=ntfy_topic,
                    ntfy_priority=ntfy_priority,
                    content=message,
                )
            except Exception as e:
                print("Ntfy 推送失败", e)
        if xxtui_key:
            try:
                message2xxtui(
                    xxtui_key=xxtui_key,
                    content=message,
                )
            except Exception as e:
                print("Xxtui 推送失败", str(e).replace(xxtui_key, "***"))
        if webhook_url:
            try:
                message2webhook(
                    webhook_url=webhook_url,
                    content=message,
                    webhook_method=webhook_method,
                    webhook_body=webhook_body,
                )
            except Exception as e:
                # 异常串可能只含 path 形态（/x?token=…），除完整 URL 外还需掩码各查询参数值
                secrets = [webhook_url] + [v for _, v in parse_qsl(urlsplit(webhook_url).query)]
                masked = str(e)
                for secret in secrets:
                    if secret:
                        masked = masked.replace(secret, "***")
                print("Webhook 推送失败", masked)
        if pushme_key:
            try:
                message2pushme(pushme_key=pushme_key, content=message)
            except Exception as e:
                print("PushMe 推送失败", str(e).replace(pushme_key, "***"))
        if qlapi:
            try:
                message2qlapi(content=message)
            except Exception as e:
                print("青龙 QLAPI 推送失败", e)
        if smtp_server and smtp_user and smtp_password:
            try:
                message2smtp(
                    smtp_server=smtp_server,
                    smtp_user=smtp_user,
                    smtp_password=smtp_password,
                    content=message,
                    smtp_port=smtp_port,
                    smtp_ssl=smtp_ssl,
                    smtp_to=smtp_to,
                )
            except Exception as e:
                print("SMTP 邮件推送失败", e)
        if pushdeer_pushkey:
            try:
                message2pushdeer(pushdeer_pushkey=pushdeer_pushkey, content=message)
            except Exception as e:
                print("PushDeer 推送失败", e)
        if wxpusher_apptoken and wxpusher_uids:
            try:
                message2wxpusher(
                    wxpusher_apptoken=wxpusher_apptoken,
                    wxpusher_uids=wxpusher_uids,
                    content=message,
                )
            except Exception as e:
                print("wxPusher 推送失败", e)


if __name__ == "__main__":
    print("message.py 各渠道请通过 config.json 通知配置触发；本模块无独立自测入口")
