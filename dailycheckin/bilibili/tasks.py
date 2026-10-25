"""Opt-in task families from BiliBiliTool, with conservative defaults."""

import hashlib
import hmac
import json
import re
import time
import uuid
from urllib.parse import quote

LIVE_HEADERS = {
    "Origin": "https://live.bilibili.com",
    "Referer": "https://live.bilibili.com/",
}
MANGA_HEADERS = {"Referer": "https://manga.bilibili.com/"}


class BiliBiliTasks:
    def __init__(self, session, cookie, account):
        self.session = session
        self.cookie = cookie
        self.account = account
        tasks = account.get("tasks", {})
        self.tasks = tasks if isinstance(tasks, dict) else {}
        self.csrf = cookie.get("bili_jct", "")
        self._wbi_mixin_key = None

    def _json(self, method, url, **kwargs):
        if not url.startswith("https://"):
            raise ValueError("Bilibili task requests must use HTTPS")
        response = self.session.request(method, url, timeout=20, verify=True, **kwargs)
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as error:
            raise RuntimeError("Bilibili returned a non-JSON response") from error

    @staticmethod
    def _data(result):
        if not isinstance(result, dict) or result.get("code") != 0:
            raise RuntimeError("Bilibili API rejected the task")
        return result.get("data") or {}

    def _run(self, name, function):
        try:
            return f"{name}: {function()}"
        except Exception as error:
            return f"{name}: 失败（{type(error).__name__}）"

    def run(self):
        results = []

        def enabled(key):
            config = self.tasks.get(key)
            if isinstance(config, dict) and "enabled" in config:
                return bool(config["enabled"])
            if key == "silver2coin":
                return bool(self.account.get("silver2coin", False))
            return False

        jobs = [
            ("漫画阅读", "manga_read", self.manga_read),
            ("漫画会员权益", "manga_privilege", self.manga_privilege),
            ("大会员积分", "vip_big_point", self.vip_big_point),
            ("银瓜子兑换", "silver2coin", self.silver2coin),
            ("B币充电", "charge", self.charge),
            ("直播抽奖", "live_lottery", self.live_lottery),
            ("批量取关", "unfollow_batched", self.unfollow_batched),
            ("粉丝牌互动", "live_fans_medal", self.live_fans_medal),
        ]
        for label, key, function in jobs:
            if enabled(key):
                results.append(self._run(label, function))
        return results

    def manga_read(self):
        config = self.tasks["manga_read"]
        comic_id = int(config.get("comic_id", 0))
        episode_id = int(config.get("episode_id", 0))
        if comic_id <= 0 or episode_id <= 0:
            raise ValueError("comic_id 和 episode_id 必须显式设置")
        result = self._json(
            "POST",
            "https://manga.bilibili.com/twirp/bookshelf.v1.Bookshelf/AddHistory",
            params={
                "platform": config.get("platform", "android"),
                "comic_id": comic_id,
                "ep_id": episode_id,
            },
            headers=MANGA_HEADERS,
        )
        self._data(result)
        return "阅读记录已上报"

    def manga_privilege(self):
        config = self.tasks["manga_privilege"]
        if int(self._profile().get("vipType", 0) or 0) == 0:
            return "非大会员，跳过"
        reason_ids = config.get("reason_ids", [1])
        if (
            not isinstance(reason_ids, list)
            or not reason_ids
            or len(reason_ids) > 10
            or any(int(reason_id) <= 0 or int(reason_id) > 100 for reason_id in reason_ids)
        ):
            raise ValueError("reason_ids 必须是 1–10 个正整数")
        results = []
        for reason_id in reason_ids:
            result = self._json(
                "POST",
                "https://manga.bilibili.com/twirp/user.v1.User/GetVipReward",
                params={"reason_id": int(reason_id)},
                headers=MANGA_HEADERS,
            )
            self._data(result)
            results.append("已领取")
        return "、".join(results)

    def vip_big_point(self):
        config = self.tasks["vip_big_point"]
        profile = self._profile()
        if int(profile.get("vipType", 0) or 0) == 0:
            return "非大会员，跳过"
        buvid = self.cookie.get("buvid3") or self.cookie.get("buvid4", "")
        combine = self._data(
            self._json(
                "GET",
                "https://api.bilibili.com/x/vip_point/task/combine",
                params={
                    "csrf": self.csrf,
                    "buvid": buvid,
                    "brand": "Samsung",
                    "channel": "bili",
                    "containerName": "AbstractWebActivity",
                    "device": "phone",
                    "mobi_app": "android",
                    "platform": "android",
                    "build": "8451100",
                    "disable_rcmd": 0,
                    "statistics": '{"appId":1,"platform":3,"version":"8.45.1","abtest":""}',
                    "t": int(time.time() * 1000),
                    "ts": int(time.time()),
                },
            )
        )
        status = self._json(
            "GET",
            "https://api.bilibili.com/x/vip/vip_center/sign_in/three_days_sign",
            params={"csrf": self.csrf},
        )
        sign_data = self._data(status)
        signed = (sign_data.get("three_day_sign") or {}).get("signed")
        if signed:
            sign_result = "已签到"
        else:
            now_ms = int(time.time() * 1000)
            response = self._json(
                "POST",
                "https://api.bilibili.com/pgc/activity/score/task/sign2",
                params={"mobi_app": "android", "csrf": self.csrf, "platform": "android"},
                json={"device": "phone", "t": now_ms, "ts": now_ms // 1000},
            )
            self._data(response)
            sign_result = "签到成功"
        details = [sign_result]
        if config.get("bonus_missions", False):
            details.extend(self._vip_point_missions(combine, ("bonus", "privilege"), config))
        if config.get("daily_missions", False):
            allowed = ("dress-view", "vipmallview", "animatetab", "filmtab", "ogvwatchnew")
            details.extend(self._vip_point_missions(combine, allowed, config))
        if config.get("experience_task", False):
            voucher = self._data(self._json("GET", "https://api.bilibili.com/x/vip/privilege/my"))
            item = next(
                (entry for entry in voucher.get("list", []) if entry.get("type") == 9),
                None,
            )
            if item and item.get("state") == 0:
                self._data(
                    self._json(
                        "POST",
                        "https://api.bilibili.com/x/vip/experience/add",
                        data={"csrf": self.csrf},
                    )
                )
                details.append("已领取大会员经验包")
            elif item and item.get("state") == 2:
                if self._watch_bangumi(config):
                    self._data(
                        self._json(
                            "POST",
                            "https://api.bilibili.com/x/vip/experience/add",
                            data={"csrf": self.csrf},
                        )
                    )
                    details.append("已完成剧集观看并领取经验包")
                else:
                    details.append("经验包需 view_bangumi_ssids，已跳过")
            else:
                details.append("经验包不可领取")
        return "；".join(details)

    def _vip_point_missions(self, combine, allowed_codes, config):
        task_info = combine.get("task_info") or combine.get("Task_info") or {}
        modules = task_info.get("modules") or task_info.get("Modules") or []
        results = []
        for module in modules:
            title = module.get("module_title") or module.get("Module_title")
            if title not in ("福利任务", "体验任务", "日常任务"):
                continue
            items = module.get("common_task_item") or module.get("Common_task_item") or []
            for task in items:
                code = task.get("task_code") or task.get("Task_code")
                state = task.get("state", task.get("State"))
                if code not in allowed_codes or state == 3:
                    continue
                try:
                    if state == 0:
                        received = self._json(
                            "POST",
                            "https://api.bilibili.com/pgc/activity/score/task/receive/v2",
                            data={"TaskCode": code},
                        )
                        self._data(received)
                    if code == "ogvwatchnew" and not self._watch_bangumi(config):
                        results.append("ogvwatchnew 缺少 view_bangumi_ssids，跳过")
                        continue
                    if code in ("dress-view", "ogvwatchnew", "bonus", "privilege"):
                        completed = self._json(
                            "POST",
                            "https://api.bilibili.com/pgc/activity/score/task/complete/v2",
                            data={"TaskCode": code},
                        )
                    elif code in ("animatetab", "filmtab"):
                        completed = self._json(
                            "POST",
                            "https://api.bilibili.com/pgc/activity/deliver/task/complete",
                            data={
                                "position": "jp_channel" if code == "animatetab" else "tv_channel",
                                "c_locale": "zh_CN",
                                "channel": "bili",
                                "s_locale": "zh_CN",
                                "build": "8451100",
                                "disable_rcmd": 0,
                                "mobi_app": "android",
                                "platform": "android",
                                "t": int(time.time() * 1000),
                                "ts": int(time.time()),
                            },
                        )
                    elif code == "vipmallview":
                        completed = self._json(
                            "POST",
                            "https://show.bilibili.com/api/activity/fire/common/event/dispatch",
                            json={"csrf": self.csrf, "eventId": "hevent_oy4b7h3epeb"},
                        )
                    else:
                        continue
                    self._data(completed)
                    results.append(f"{code} 已处理")
                except Exception as error:
                    results.append(f"{code} 失败（{type(error).__name__}）")
        return results

    def _watch_bangumi(self, config):
        season_ids = config.get("view_bangumi_ssids", [])
        if not isinstance(season_ids, list) or not season_ids:
            return False
        season_id = int(season_ids[0])
        result = self._json(
            "GET",
            "https://api.bilibili.com/pgc/view/web/season",
            params={"season_id": season_id},
        )
        season = self._data(result).get("result") or {}
        episodes = season.get("episodes") or []
        if not episodes:
            return False
        episode = episodes[0]
        duration = int(episode.get("duration", 0) or 0) // 1000
        played = min(1800, max(905, duration or 905))
        payload = {
            "Aid": episode.get("aid"),
            "Cid": episode.get("cid"),
            "Bvid": episode.get("bvid"),
            "Epid": episode.get("ep_id"),
            "Sid": season_id,
            "Mid": self.cookie.get("DedeUserID", "0"),
            "Csrf": self.csrf,
            "Played_time": played,
            "Real_played_time": played,
            "Realtime": played,
            "Start_ts": int(time.time()) - played,
            "Type": 4,
            "Sub_type": 1,
            "Dt": 2,
            "Play_type": 3,
        }
        self._data(
            self._json(
                "POST",
                "https://api.bilibili.com/x/click-interface/web/heartbeat",
                params={"aid": episode.get("aid"), "played_time": played},
                data=payload,
                headers={"Referer": "https://www.bilibili.com/", "Origin": "https://www.bilibili.com"},
            )
        )
        return True

    def silver2coin(self):
        status = self._data(self._json("GET", "https://api.live.bilibili.com/xlive/revenue/v1/wallet/getStatus"))
        if int(status.get("silver_2_coin_left", 0) or 0) <= 0:
            return "今日兑换次数已用完"
        result = self._json(
            "POST",
            "https://api.live.bilibili.com/xlive/revenue/v1/wallet/silver2coin",
            data={"csrf": self.csrf, "csrf_token": self.csrf},
        )
        data = self._data(result)
        return f"兑换成功，硬币余额 {data.get('coin', '未知')}"

    def charge(self):
        config = self.tasks["charge"]
        target = str(config.get("target_up_id", "")).strip()
        amount = int(config.get("amount", 0))
        cap = int(config.get("max_amount", 0))
        if not target.isdigit() or amount <= 0 or cap <= 0 or amount > cap:
            raise ValueError("需设置目标 UID、正数金额和不低于金额的 max_amount")
        profile = self._profile()
        if int(profile.get("vipType", 0) or 0) != 2:
            return "非年度大会员，跳过"
        wallet = profile.get("wallet") or {}
        available = float(wallet.get("coupon_balance", 0) or 0)
        if amount > available:
            raise ValueError("充电金额超过可用 B 币券余额")
        result = self._json(
            "POST",
            "https://api.bilibili.com/x/ugcpay/web/v2/trade/elec/pay/quick",
            data={
                "bp_num": amount,
                "is_bp_remains_prior": "true",
                "up_mid": target,
                "otype": "up",
                "oid": target,
                "csrf": self.csrf,
            },
        )
        data = self._data(result)
        if (data.get("status") or 0) != 4:
            raise RuntimeError("Bilibili did not confirm the charge")
        comment = str(config.get("comment", "")).strip()
        if comment:
            order_id = data.get("order_no") or data.get("order_id")
            if order_id:
                self._data(
                    self._json(
                        "POST",
                        "https://api.bilibili.com/x/ugcpay/trade/elec/message",
                        data={"order_id": order_id, "message": comment, "csrf": self.csrf},
                    )
                )
        return f"已向 UID {target} 充电 {amount} B币券"

    def live_lottery(self):
        config = self.tasks["live_lottery"]
        max_rooms = min(max(int(config.get("max_rooms", 0)), 0), 50)
        max_joins = min(max(int(config.get("max_joins", 0)), 0), 10)
        if max_rooms == 0 or max_joins == 0:
            raise ValueError("max_rooms 和 max_joins 必须分别设置为 1–50、1–10")
        auto_group = bool(config.get("auto_group_followings", False))
        baseline = self._following_ids() if auto_group else set()
        areas = (
            self._data(
                self._json(
                    "GET",
                    "https://api.live.bilibili.com/xlive/web-interface/v1/index/getWebAreaList",
                    params={"source_id": 2},
                    headers=LIVE_HEADERS,
                )
            ).get("data")
            or []
        )
        denied = {str(x) for x in config.get("deny_uids", [])}
        include = str(config.get("include_award_names", ""))
        exclude = str(config.get("exclude_award_names", "舰|船|航海|代金券|自拍|写真|提督"))
        joined = 0
        followed_uids = []
        inspected = 0
        for area in areas:
            if inspected >= max_rooms:
                break
            rooms = (
                self._data(
                    self._json(
                        "GET",
                        "https://api.live.bilibili.com/room/v3/area/getRoomList",
                        params={
                            "platform": "web",
                            "parent_area_id": area.get("id", 0),
                            "area_id": 0,
                            "sort_type": "online",
                            "page": 1,
                            "page_size": min(99, max_rooms - inspected),
                        },
                        headers=LIVE_HEADERS,
                    )
                ).get("list")
                or []
            )
            for room in rooms:
                if inspected >= max_rooms:
                    break
                inspected += 1
                pendant = ((room.get("pendant_info") or {}).get("2") or {}).get("pendent_id")
                if pendant not in (504, 1432) or str(room.get("uid")) in denied:
                    continue
                check = self._data(
                    self._json(
                        "GET",
                        "https://api.live.bilibili.com/xlive/lottery-interface/v1/Anchor/Check",
                        params={"roomid": room.get("roomid")},
                        headers=LIVE_HEADERS,
                    )
                )
                if check.get("status") not in (1, "1"):
                    continue
                award = str(check.get("award_name", ""))
                if include and not any(part in award for part in include.split("|")):
                    continue
                if exclude and any(part and part in award for part in exclude.split("|")):
                    continue
                gift_price = check.get("gift_price")
                if gift_price is None or float(gift_price) != 0:
                    continue
                if "require_type" not in check:
                    continue
                requirement = int(check.get("require_type") or 0)
                if requirement not in (0, 1):
                    continue
                if requirement == 1 and not config.get("allow_follow_required", False):
                    continue
                result = self._json(
                    "POST",
                    "https://api.live.bilibili.com/xlive/lottery-interface/v1/Anchor/Join",
                    data={
                        "id": check.get("id"),
                        "gift_id": check.get("gift_id"),
                        "gift_num": check.get("gift_num"),
                        "csrf": self.csrf,
                        "csrf_token": self.csrf,
                        "visit_id": uuid.uuid4().hex,
                        "platform": "pc",
                    },
                    headers=LIVE_HEADERS,
                )
                self._data(result)
                joined += 1
                if requirement == 1:
                    followed_uids.append(str(room.get("uid", "")))
                if joined >= max_joins:
                    break
            if joined >= max_joins:
                break
        grouped = 0
        if auto_group and followed_uids:
            latest = self._following_ids()
            added = [uid for uid in latest if uid not in baseline and uid in followed_uids]
            grouped = self._group_followings(added, str(config.get("group_name", "天选时刻")))
        return f"检查 {inspected} 个房间，参加 {joined} 个抽奖，整理关注分组 {grouped} 人"

    def _following_ids(self):
        profile = self._profile()
        uid = int(profile.get("mid", 0) or 0)
        result = self._json(
            "GET",
            "https://api.bilibili.com/x/relation/followings",
            params={"vmid": uid, "pn": 1, "ps": 50, "order": "desc", "order_type": "attention", "jsonp": "jsonp"},
        )
        data = self._data(result)
        return {str(item.get("mid")) for item in (data.get("list") or []) if item.get("mid")}

    def _group_followings(self, uids, group_name):
        if not uids or not group_name:
            return 0
        profile = self._profile()
        uid = str(profile.get("mid", ""))
        referer = f"https://space.bilibili.com/{uid}/fans/follow"
        tags = self._data(
            self._json(
                "GET",
                "https://api.bilibili.com/x/relation/tags",
                params={"jsonp": "jsonp"},
                headers={"Referer": referer},
            )
        )
        tag = next((item for item in (tags or []) if item.get("name") == group_name), None)
        if tag is None:
            tag = self._data(
                self._json(
                    "POST",
                    "https://api.bilibili.com/x/relation/tag/create",
                    params={"cross_domain": "true"},
                    data={"tag": group_name, "csrf": self.csrf},
                    headers={"Referer": referer},
                )
            )
        tag_id = tag.get("tagid")
        if not tag_id:
            return 0
        self._data(
            self._json(
                "POST",
                "https://api.bilibili.com/x/relation/tags/copyUsers",
                data={"fids": ",".join(uids), "tagids": str(tag_id), "csrf": self.csrf, "jsonp": "jsonp"},
                headers={"Referer": referer},
            )
        )
        return len(uids)

    def unfollow_batched(self):
        config = self.tasks["unfollow_batched"]
        group_name = str(config.get("group_name", "")).strip()
        count = int(config.get("count", 0))
        if not group_name or count <= 0 or count > 20:
            raise ValueError("需设置分组名，取关数必须为 1–20")
        profile = self._profile()
        uid = str(profile.get("mid", ""))
        tags = self._data(
            self._json(
                "GET",
                "https://api.bilibili.com/x/relation/tags",
                params={"jsonp": "jsonp"},
                headers={"Referer": f"https://space.bilibili.com/{uid}/fans/follow"},
            )
        )
        tag = next((x for x in (tags or []) if x.get("name") == group_name), None)
        if not tag:
            raise ValueError("关注分组不存在")
        page = max((int(tag.get("count", 0)) + 19) // 20, 1)
        following_data = self._data(
            self._json(
                "GET",
                "https://api.bilibili.com/x/relation/tag",
                params={"mid": uid, "tagid": tag.get("tagid"), "pn": page, "ps": 20},
                headers={"Referer": f"https://space.bilibili.com/{uid}/fans/follow"},
            )
        )
        accounts = list(following_data.get("list") or [])
        accounts.reverse()
        keep = {str(x) for x in config.get("retain_uids", [])}
        targets = [item for item in accounts if str(item.get("mid")) not in keep][:count]
        removed = 0
        for item in targets:
            result = self._json(
                "POST",
                "https://api.bilibili.com/x/relation/modify",
                data={
                    "fid": item.get("mid"),
                    "act": 2,
                    "re_src": 11,
                    "csrf": self.csrf,
                    "jsonp": "jsonp",
                },
                headers={"Referer": f"https://space.bilibili.com/{uid}/fans/follow"},
            )
            self._data(result)
            removed += 1
        return f"按分组 {group_name} 取关 {removed} 人"

    def live_fans_medal(self):
        config = self.tasks["live_fans_medal"]
        allow_uids = {str(x) for x in config.get("anchor_uids", [])}
        if not allow_uids:
            raise ValueError("请配置 anchor_uids 白名单")
        if len(allow_uids) > 5:
            raise ValueError("anchor_uids 最多允许 5 个 UID")
        like_count = min(max(int(config.get("like_count", 0)), 0), 5000)
        danmaku_count = min(max(int(config.get("danmaku_count", 0)), 0), 20)
        watch_minutes = min(max(int(config.get("watch_minutes", 0)), 0), 15)
        medals = []
        for page in range(1, 101):
            panel = self._data(
                self._json(
                    "GET",
                    "https://api.live.bilibili.com/xlive/app-ucenter/v1/fansMedal/panel",
                    params={"page": page, "page_size": 10},
                    headers=LIVE_HEADERS,
                )
            )
            items = (panel.get("special_list") or []) + (panel.get("list") or [])
            for item in items:
                medal = item.get("medal") or {}
                room = item.get("room_info") or {}
                if str(medal.get("target_id")) in allow_uids and int(room.get("room_id", 0) or 0):
                    medals.append((medal, room))
            page_info = panel.get("page_info") or {}
            if not page_info.get("has_more"):
                break
        results = []
        like_budget = like_count
        danmaku_budget = danmaku_count
        watch_budget = watch_minutes * 60
        for medal, room in medals:
            task_progress = self._data(
                self._json(
                    "GET",
                    "https://api.live.bilibili.com/xlive/app-ucenter/v1/fansMedal/GetActivatedMedalInfo",
                    params={
                        "target_id": medal["target_id"],
                        "csrf": self.csrf,
                        "web_location": "444.260",
                    },
                    headers=LIVE_HEADERS,
                )
            )
            remaining_like = self._medal_task_remaining(task_progress, "like")
            remaining_danmaku = self._medal_task_remaining(task_progress, "sendDanmu")
            remaining_watch = self._medal_task_remaining(task_progress, "watchLive")
            task_like_budget = min(like_budget, remaining_like)
            starting_like_budget = task_like_budget
            while task_like_budget:
                click_time = min(10, task_like_budget)
                result = self._json(
                    "POST",
                    "https://api.live.bilibili.com/xlive/app-ucenter/v1/like_info_v3/like/likeReportV3",
                    data={
                        "click_time": click_time,
                        "room_id": room["room_id"],
                        "uid": self.cookie.get("DedeUserID", ""),
                        "anchor_id": medal["target_id"],
                        "csrf_token": self.csrf,
                        "csrf": self.csrf,
                    },
                    headers=LIVE_HEADERS,
                )
                self._data(result)
                like_budget -= click_time
                task_like_budget -= click_time
                time.sleep(3)
            if starting_like_budget > task_like_budget:
                results.append("点赞已发送")
            task_danmaku_budget = min(danmaku_budget, remaining_danmaku)
            if task_danmaku_budget:
                content = str(config.get("danmaku_content", "")).strip()
                if not content or len(content) > 30:
                    raise ValueError("danmaku_content 需为 1–30 个字符")
                if config.get("danmaku_only_when_offline", False):
                    room_status = self._data(
                        self._json(
                            "GET",
                            "https://api.live.bilibili.com/room/v1/Room/get_info",
                            params={"room_id": room["room_id"], "from": "room"},
                            headers=LIVE_HEADERS,
                        )
                    )
                    if int(room_status.get("live_status", 0) or 0) == 1:
                        task_danmaku_budget = 0
                        results.append("直播中，按配置跳过弹幕")
                if task_danmaku_budget:
                    for _ in range(task_danmaku_budget):
                        result = self._json(
                            "POST",
                            "https://api.live.bilibili.com/msg/send",
                            data={
                                "bubble": 0,
                                "mode": 1,
                                "fontsize": 25,
                                "color": 16777215,
                                "msg": content,
                                "roomid": room["room_id"],
                                "csrf": self.csrf,
                                "csrf_token": self.csrf,
                                "rnd": int(time.time()),
                            },
                            headers=LIVE_HEADERS,
                        )
                        self._data(result)
                        time.sleep(7)
                    danmaku_budget -= task_danmaku_budget
                    results.append("弹幕已发送")
            target_watch = min(watch_budget, remaining_watch)
            if target_watch:
                watched = self._watch_live_room(medal, room, target_watch)
                watch_budget -= watched
                results.append(f"观看心跳 {watched // 60} 分钟")
        if not medals:
            return "白名单内没有可用粉丝牌"
        return "、".join(results) if results else "没有启用互动项"

    @staticmethod
    def _medal_task_remaining(data, action):
        task = next(
            (item for item in (data.get("task_info") or []) if item.get("jump_type") == action),
            None,
        )
        if not task or task.get("is_done"):
            return 0
        numbers = re.findall(r"\d+(?:\.\d+)?", str(task.get("title", "")))
        if not numbers:
            return 0
        total = float(numbers[0]) * (60 if action == "watchLive" else 1)
        progress = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", str(task.get("sub_title", "")))
        if not progress:
            return int(total) if not data.get("is_lighted") else 0
        current, limit = map(float, progress.groups())
        return max(0, int((limit - current) * total + 0.999999))

    def _profile(self):
        return self._data(self._json("GET", "https://api.bilibili.com/x/web-interface/nav"))

    @staticmethod
    def _wbi_mix_key(img_key, sub_key):
        table = [
            46,
            47,
            18,
            2,
            53,
            8,
            23,
            32,
            15,
            50,
            10,
            31,
            58,
            3,
            45,
            35,
            27,
            43,
            5,
            49,
            33,
            9,
            42,
            19,
            29,
            28,
            14,
            39,
            12,
            38,
            41,
            13,
            37,
            48,
            7,
            16,
            24,
            55,
            40,
            61,
            26,
            17,
            0,
            1,
            60,
            51,
            30,
            4,
            22,
            25,
            54,
            21,
            56,
            59,
            6,
            63,
            57,
            62,
            11,
            36,
            20,
            34,
            44,
            52,
        ]
        source = img_key + sub_key
        return "".join(source[index] for index in table)[:32]

    def _wbi_sign(self, params):
        if self._wbi_mixin_key is None:
            profile = self._profile()
            wbi = profile.get("wbi_img") or {}
            img = (wbi.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
            sub = (wbi.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
            if len(img) < 32 or len(sub) < 32:
                raise RuntimeError("missing WBI signing keys")
            self._wbi_mixin_key = self._wbi_mix_key(img, sub)
        mixin = self._wbi_mixin_key
        values = dict(params)
        values["wts"] = int(time.time())
        encoded = []
        for key, raw_value in sorted(values.items()):
            value = re.sub(r"[!'()*]", "", str(raw_value))
            encoded.append(f"{key}={quote(value, safe='-_.~')}")
        query = "&".join(encoded)
        values["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
        return values

    def _watch_live_room(self, medal, room, target_seconds):
        room_id = int(room["room_id"])
        info = self._data(
            self._json(
                "GET",
                "https://api.live.bilibili.com/room/v1/Room/get_info",
                params={"room_id": room_id, "from": "room"},
                headers=LIVE_HEADERS,
            )
        )
        if int(info.get("live_status", 0)) != 1:
            return 0
        anchor = int(medal["target_id"])
        live_buvid = self.cookie.get("LIVE_BUVID", "")
        if not live_buvid:
            raise ValueError("LIVE_BUVID missing")
        if int(info.get("parent_area_id", 0) or 0) <= 0 or int(info.get("area_id", 0) or 0) <= 0:
            raise ValueError("直播间分区信息无效")
        uid_uuid = str(uuid.uuid4())
        device = json.dumps([live_buvid, uid_uuid], separators=(",", ":"))
        area_id = int(info.get("area_id", 0))
        parent_id = int(info.get("parent_area_id", 0))
        payload = {
            "id": json.dumps([parent_id, area_id, 0, room_id]),
            "ruid": anchor,
            "ts": int(time.time() * 1000),
            "is_patch": 0,
            "heart_beat": "[]",
            "ua": self.session.headers.get("User-Agent", "Mozilla/5.0"),
            "csrf_token": self.csrf,
            "csrf": self.csrf,
            "visit_id": "",
            "device": device,
            "web_location": "444.8",
        }
        enter = self._json(
            "POST",
            "https://live-trace.bilibili.com/xlive/data-interface/v1/x25Kn/E",
            data=self._wbi_sign(payload),
            headers=LIVE_HEADERS,
        )
        state = self._data(enter)
        interval = int(state.get("heartbeat_interval", 0) or 0)
        if interval <= 0 or interval > 300 or not state.get("secret_key"):
            raise RuntimeError("invalid heartbeat parameters")
        rules = state.get("secret_rule") or []
        if not isinstance(rules, list) or not rules:
            raise RuntimeError("invalid heartbeat signature rules")
        watched = 0
        sequence = 1
        while watched < target_seconds:
            time.sleep(interval)
            live_status = self._data(
                self._json(
                    "GET",
                    "https://api.live.bilibili.com/room/v1/Room/get_info",
                    params={"room_id": room_id, "from": "room"},
                    headers=LIVE_HEADERS,
                )
            )
            if int(live_status.get("live_status", 0) or 0) != 1:
                break
            timestamp = int(time.time() * 1000)
            signed_payload = {
                "platform": "web",
                "parent_id": parent_id,
                "area_id": area_id,
                "seq_id": sequence,
                "room_id": room_id,
                "buvid": live_buvid,
                "uuid": uid_uuid,
                "ets": state.get("timestamp"),
                "time": interval,
                "ts": timestamp,
            }
            signed_text = json.dumps(signed_payload, separators=(",", ":"), ensure_ascii=False)
            signature = signed_text
            for rule in rules:
                algorithms = {0: "md5", 1: "sha1", 2: "sha256", 3: "sha224", 4: "sha512", 5: "sha384"}
                algorithm = algorithms.get(int(rule))
                if not algorithm:
                    raise RuntimeError("unsupported heartbeat signature rule")
                signature = hmac.new(str(state["secret_key"]).encode(), signature.encode(), algorithm).hexdigest()
            heartbeat = {
                "s": signature,
                "id": json.dumps([parent_id, area_id, sequence, room_id]),
                "ets": state.get("timestamp"),
                "benchmark": state.get("secret_key"),
                "time": interval,
                "ts": timestamp,
                "ua": self.session.headers.get("User-Agent", "Mozilla/5.0"),
                "csrf_token": self.csrf,
                "csrf": self.csrf,
                "visit_id": "",
                "device": device,
                "ruid": anchor,
                "trackid": "-99998",
                "web_location": "444.8",
            }
            result = self._json(
                "POST",
                "https://live-trace.bilibili.com/xlive/data-interface/v1/x25Kn/X",
                data=self._wbi_sign(heartbeat),
                headers=LIVE_HEADERS,
            )
            state = self._data(result)
            watched += interval
            sequence += 1
        return watched
