"""3DM 论坛任务，流程参考 https://github.com/lksky8/sign-ql/blob/main/3dmgame.py。"""
import random
import re
import time
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from lxml import etree

from dailycheckin import CheckIn


class ThreeDMGame(CheckIn):
    name = "3DM游戏论坛"
    base = "https://bbs.3dmgame.com/"

    def __init__(self, check_item):
        self.check_item = check_item
        self.session = requests.Session()
        self.session.headers.update({
            "Cookie": check_item.get("cookie", ""),
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/146.0.0.0 Safari/537.36",
            "Referer": self.base,
        })
        self.messages = []
        self.outcome = "success"

    def log(self, message):
        self.messages.append(message)
        print(message)

    def get(self, path):
        url = urljoin(self.base, path)
        if urlparse(url).netloc != "bbs.3dmgame.com" or urlparse(url).scheme != "https":
            raise ValueError("论坛页面包含无效的站外链接")
        response = self.session.get(url, timeout=20)
        response.raise_for_status()
        return response.text

    @staticmethod
    def task_id(link):
        values = parse_qs(urlparse(link).query).get("id", [])
        return values[0] if values and values[0].isdigit() else ""

    def user_info(self):
        page = etree.HTML(self.get("home.php?mod=spacecp&ac=credit&showcredit=1"))
        users = page.xpath('//*[@id="hd"]/div/div[1]/p/strong/a/text()') if page is not None else []
        if not users:
            raise ValueError("无法获取用户信息，Cookie 可能失效或页面异常")
        points = page.xpath('//*[@id="extcreditmenu"]/text()')
        gold = page.xpath('//*[@id="ct"]/div[1]/div/ul[2]/li[1]/text()')
        self.log(f"用户: {users[0].strip()}，积分: {''.join(points).strip()}，金元: {''.join(gold).strip()}")

    def task_rows(self, path):
        page = etree.HTML(self.get(path))
        if page is None:
            raise ValueError("论坛任务页面为空")
        return page.xpath('//div[@class="ptm"]//table//tr')

    def draw(self, task_id, name):
        text = self.get(f"home.php?mod=task&do=draw&id={task_id}")
        if "恭喜您，任务已成功完成" in text:
            self.log(f"任务《{name}》：奖励领取成功")
        else:
            self.outcome = "partial"
            self.log(f"任务《{name}》：奖励未领取，请查看论坛任务状态")

    def apply_tasks(self):
        for row in self.task_rows("home.php?mod=task"):
            links = row.xpath('.//td[4]/a[contains(@href, "do=apply")]/@href')
            names = row.xpath('.//td[2]//h3/a/text()')
            task_id = self.task_id(links[0]) if links else ""
            if not task_id:
                continue
            name = names[0].strip() if names else task_id
            text = self.get(f"home.php?mod=task&do=apply&id={task_id}")
            if "do=draw" in text:
                self.draw(task_id, name)
            elif "任务申请成功" in text:
                self.log(f"任务《{name}》：申请成功")
            else:
                self.outcome = "partial"
                self.log(f"任务《{name}》：未能申请，请查看论坛任务状态")
            time.sleep(1)

    def reply(self, tid, fid, formhash):
        try:
            response = requests.get(
                "https://www.mxnzp.com/api/jokes/list",
                params={"page": 1, "app_id": "vqohyieoq7qklmgp", "app_secret": "FCc9Uf0h1c0LNkqeLRolebStTGfds3Fx"},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            message = data["data"]["list"][0]["content"] if data.get("code") == 1 else ""
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
            message = ""
        message = message or "我是新玩家，搞不懂" + str(random.randint(0, 9))
        response = self.session.post(
            self.base + f"forum.php?mod=post&action=reply&fid={fid}&tid={tid}&extra=page%3D1&replysubmit=yes&infloat=yes&handlekey=fastpost&inajax=1",
            data={"file": "", "message": message, "posttime": str(int(time.time())), "formhash": formhash, "usesig": "1", "subject": "  "},
            timeout=20,
        )
        response.raise_for_status()
        return "回复发布成功" in response.text

    def do_task(self, task_id, name):
        text = self.get(f"home.php?mod=task&do=view&id={task_id}")
        if "static/image/task/reward.gif" in text or "完成此任务所需条件" in text:
            self.draw(task_id, name)
            return
        tree = etree.HTML(text)
        links = tree.xpath("//table[@class='tfm']//td[@class='bbda']/a/@href") if tree is not None else []
        counts = tree.xpath("//table[@class='tfm']//td[@class='bbda'][contains(., '次')]/text()[normalize-space()]") if tree is not None else []
        match = re.search(r"(\d+)\s*次", " ".join(counts))
        if not links or not match or not 1 <= int(match.group(1)) <= 5:
            self.log(f"任务《{name}》：条件无法识别或回复次数超过5次，跳过")
            return
        page = self.get(links[0])
        if "thread" not in links[0]:
            tids = re.findall(r"mod=redirect&tid=(\d+)&goto", page)
            if not tids:
                self.log(f"任务《{name}》：未找到可回复主题")
                return
            page = self.get(f"thread-{random.choice(tids)}-1-1.html")
        formhash = re.search(r'name=["\']formhash["\']\s+value=["\'](\w+)', page)
        fid = re.search(r"fid\s*=\s*parseInt\(['\"](\d+)", page)
        tid = re.search(r"tid\s*=\s*parseInt\(['\"](\d+)", page)
        if not all((formhash, fid, tid)):
            self.log(f"任务《{name}》：帖子参数缺失，跳过")
            return
        successes = failures = 0
        for _ in range(int(match.group(1))):
            for attempt in range(3):
                try:
                    replied = self.reply(tid.group(1), fid.group(1), formhash.group(1))
                except Exception:
                    failures += 1
                    self.outcome = "partial"
                    self.log(f"任务《{name}》：回帖成功 {successes} 次，失败 {failures} 次")
                    raise
                if replied:
                    successes += 1
                else:
                    failures += 1
                    self.outcome = "partial"
                self.log(f"任务《{name}》：回帖成功 {successes} 次，失败 {failures} 次")
                if replied:
                    break
                if attempt < 2:
                    time.sleep(10)
            else:
                self.log(f"任务《{name}》：回复失败，停止该任务")
                return
            time.sleep(35)
        self.draw(task_id, name)

    def main(self):
        if not self.check_item.get("cookie"):
            raise ValueError("请配置 3DM 论坛 Cookie")
        try:
            self.user_info()
            self.apply_tasks()
            for row in self.task_rows("home.php?mod=task&item=doing"):
                links = row.xpath('.//td[2]//h3/a/@href')
                names = row.xpath('.//td[2]//h3/a/text()')
                task_id = self.task_id(links[0]) if links else ""
                if task_id:
                    self.do_task(task_id, names[0].strip() if names else task_id)
                    time.sleep(3)
            if len(self.messages) == 1:
                self.log("没有可处理的任务")
            return "\n".join(self.messages)
        finally:
            self.session.close()
