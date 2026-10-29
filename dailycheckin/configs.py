import json
import os
import re

from dailycheckin import CheckIn


def checkin_map():
    result = {}
    for cls in CheckIn.__subclasses__():
        check_name = cls.__name__.upper()
        if check_name:
            result[check_name] = (cls.name, cls)
    return result


checkin_map = checkin_map()

notice_map = {
    "BARK_URL": "",
    "BARK_TITLE": "",
    "BARK_GROUP": "",
    "BARK_ICON": "",
    "BARK_SOUND": "",
    "BARK_URL_JUMP": "",
    "COOLPUSHEMAIL": "",
    "COOLPUSHQQ": "",
    "COOLPUSHSKEY": "",
    "COOLPUSHWX": "",
    "DINGTALK_ACCESS_TOKEN": "",
    "DINGTALK_SECRET": "",
    "FSKEY": "",
    "FSSECRET": "",
    "PUSHPLUS_TOKEN": "",
    "PUSHPLUS_TOPIC": "",
    "WPUSH_APIKEY": "",
    "WPUSH_CHANNEL": "",
    "WPUSH_TOPIC_CODE": "",
    "QMSG_KEY": "",
    "QMSG_TYPE": "",
    "QMSG_URL": "",
    "QMSG_QQ": "",
    "QYWX_AGENTID": "",
    "QYWX_CORPID": "",
    "QYWX_CORPSECRET": "",
    "QYWX_KEY": "",
    "QYWX_TOUSER": "",
    "QYWX_MEDIA_ID": "",
    "QYWX_ORIGIN": "",
    "SCKEY": "",
    "SENDKEY": "",
    "TG_API_HOST": "",
    "TG_BOT_TOKEN": "",
    "TG_PROXY": "",
    "TG_USER_ID": "",
    "MERGE_PUSH": "",
    "XXTUI_KEY": "",
    "WXPUSHER_TK": "",
    "WXPUSHER_UID": "",
    "GOTIFY_URL": "",
    "GOTIFY_TOKEN": "",
    "GOTIFY_PRIORITY": "",
    "NTFY_URL": "",
    "NTFY_TOPIC": "",
    "NTFY_PRIORITY": "",
}


def env2list(key):
    try:
        value = json.loads(os.getenv(key, []).strip()) if os.getenv(key) else []
        if not isinstance(value, list):
            value = []
    except Exception as e:
        print(e)
        value = []
    return value


def env2str(key):
    try:
        value = os.getenv(key, "") if os.getenv(key) else ""
        if isinstance(value, str):
            value = value.strip()
        elif isinstance(value, bool):
            pass
        else:
            value = None
    except Exception as e:
        print(e)
        value = None
    return value


def wps_env_accounts():
    """读取青龙 WPS/wps JSON，不在错误消息中输出凭据。"""
    raw = os.getenv("WPS") or os.getenv("wps") or ""
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith('"wps"') or raw.startswith('"WPS"'):
        raw = "{" + raw + "}"
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        print("WPS 环境变量不是有效的 JSON，请检查配置格式")
        return []
    if isinstance(value, dict):
        value = value.get("wps", value.get("WPS", value))
        if isinstance(value, dict):
            value = value.get("accounts")
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        print("WPS 环境变量格式错误：accounts 必须是账号对象数组")
        return []
    return value


def get_checkin_info(data):
    result = {}
    if isinstance(data, dict):
        for one in checkin_map.keys():
            result[one.lower()] = data.get(one, [])
    else:
        for one in checkin_map.keys():
            result[one.lower()] = [] if one == "WPS" else env2list(one)
    if "WPS" in checkin_map and not result.get("wps"):
        result["wps"] = wps_env_accounts()
    if "DIDI" in checkin_map and not result.get("didi"):
        accounts = []
        for entry in os.getenv("DD_TOKENS", "").split("&"):
            entry = entry.strip()
            if not entry:
                continue
            if "#" in entry:
                name, token = entry.split("#", 1)
                if token.strip():
                    accounts.append({"account_name": name.strip(), "token": token.strip()})
            else:
                accounts.append({"token": entry})
        result["didi"] = accounts
    if "POJIE52" in checkin_map and not result.get("pojie52"):
        raw = os.getenv("POJIE52_COOKIE", "").replace("\r\n", "\n").replace("\r", "\n").strip()
        cookies = [raw] if raw else []
        for separator in ("\n", "&", "#"):
            if separator in raw:
                cookies = raw.split(separator)
                break
        result["pojie52"] = [{"cookie": cookie.strip()} for cookie in cookies if cookie.strip()]
    if "THREEDMGAME" in checkin_map and not result.get("threedmgame"):
        cookies = os.getenv("bbs3dmck", "")
        result["threedmgame"] = [
            {"cookie": cookie.strip()} for cookie in re.split(r"[@&\n]+", cookies) if cookie.strip()
        ]
    return result


def get_notice_info(data):
    result = {}
    if isinstance(data, dict):
        for one in notice_map.keys():
            result[one.lower()] = data.get(one, None)
    else:
        for one in notice_map.keys():
            result[one.lower()] = env2str(one)
    return result
