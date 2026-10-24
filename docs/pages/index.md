<div align="center">

<img src="https://socialify.git.ci/ByteRax/dailycheckin_plus/image?font=Rokkitt&forks=1&issues=1&language=1&name=1&owner=1&pattern=Circuit%20Board&pulls=1&stargazers=1&theme=Dark">

<h1>DailyCheckIn Plus</h1>

基于「Docker」/「青龙面板」/「群晖」/「本地」的每日签到脚本

fork 自 [Sitoi/dailycheckin](https://github.com/Sitoi/dailycheckin)，持续吸收社区修复

<!-- SHIELD GROUP -->
<div id="shield">

<style>
#shield img {
    display: inline-block;
}
</style>

[![][github-releases-shield]][github-releases-link]
[![][github-release-date-shield]][github-release-date-link]
[![][github-stars-shield]][github-stars-link]
[![][github-forks-shield]][github-forks-link]
[![][github-issues-shield]][github-issues-link]
[![][github-contributors-shield]][github-contributors-link]

[![][python-version-shield]][python-version-link]
[![][ghcr-shield]][ghcr-link]
[![][github-license-shield]][github-license-link]

<!-- SHIELD GROUP -->
</div>
</div>

## ✨ 特性

- 📦 支持源码（git）安装与 GitHub Release 安装包安装
- 💻 支持多个平台部署
- ⚙️ 支持多个平台签到
- 📢 支持多个平台通知
- ♾️ 支持多个账号签到（支持 `--accounts` 按账号序号执行）
- 🕗 支持定时任务设置
- 🆙 支持镜像更新 / git 更新

## 🚀 快速开始

### Docker（推荐）

```bash copy
curl https://raw.githubusercontent.com/ByteRax/dailycheckin_plus/main/docker_start.sh | bash
```

镜像地址：`ghcr.io/byterax/dailycheckin_plus:latest`（amd64 / arm64）。

### 源码安装（Python 3.9+）

```bash copy
pip install "dailycheckin @ git+https://github.com/ByteRax/dailycheckin_plus@main"
```

也可以从 [GitHub Releases](https://github.com/ByteRax/dailycheckin_plus/releases) 下载 sdist / wheel 安装包后本地安装。

> 本 fork 不发布 PyPI。PyPI 上的 `dailycheckin` 包属于上游项目，请勿与本仓库混用。

## 🦄 教程

[https://byterax.github.io/dailycheckin_plus/](https://byterax.github.io/dailycheckin_plus/)

## 🧾 列表

🟢: 正常运行 🔴: 脚本暂不可用 🔵: 可以执行(需更新) 🟡: 待测试 🟤: 看脸

| 状态 | 任务名称  | 名称网站                                                   | 检查日期 | 备注                                                                         |
| ---- | --------- | ---------------------------------------------------------- | -------- | ---------------------------------------------------------------------------- |
| 🟢️  | KGQQ      | [全民 K 歌](https://kg.qq.com/index-pc.html)               | 25.09.28 | 每日签到获取鲜花 每日大约 120 鲜花左右                                       |
| 🟢️  | YOUDAO    | [有道云笔记](https://note.youdao.com/web/)                 | 25.09.28 | 每日签到获取存储空间                                                         |
| 🟢️  | TIEBA     | [百度贴吧](https://tieba.baidu.com/index.html)             | 25.09.28 | 贴吧每日签到                                                                 |
| 🟢️  | BAIDUWP   | [百度网盘](https://pan.baidu.com/wap/svip/growth/task)     | 25.09.28 | 百度网盘会员签到和答题功能                                                   |
| 🟢️  | BILIBILI  | [BiliBili](https://www.bilibili.com/)                      | 25.09.28 | 漫画签到，每日经验任务，自动投币，银瓜子换硬币等功能                         |
| 🟢️  | V2EX      | [V2EX](https://www.v2ex.com/)                              | 25.09.28 | 铜币奖励                                                                     |
| 🟢️  | ACFUN     | [AcFun](https://www.acfun.cn/)                             | 25.09.28 | 每日签到香蕉                                                                 |
| 🟢️  | IQIYI     | [爱奇艺](https://www.iqiyi.com/)                           | 25.09.28 | ① VIP7 每月免费领白金会员；② 抽白金会员 5 次；③ 摇一摇抽奖 3 次；④ 抽奖 3 次 |
| 🟢️  | SMZDM     | [什么值得买](https://www.smzdm.com/)                       | 24.02.20 | 签到和抽奖                                                                   |
| 🟢️  | ALIYUN    | [阿里云盘](https://www.aliyundrive.com/drive/)             | 24.02.20 | 签到获取免费会员和空间                                                       |
| 🟢️  | ENSHAN    | [恩山无线论坛](https://www.right.com.cn/forum/)            | 24.02.20 | 签到获取硬币和积分                                                           |
| 🟢️  | FNNASCLUB | [飞牛 Nas](https://club.fnnas.com/)                        | 25.12.09 | 签到奖励                                                                     |
| 🟢️  | AOLAXING  | [奥拉星](http://www.100bt.com/m/creditMall/?gameId=2#task) | 24.02.20 | 签到获取积分                                                                 |
| 🟢️  | IMAOTAI   | i 茅台                                                     | 25.09.28 | 申购生肖茅台                                                                 |
| 🟤   | MIMOTION  | 小米运动                                                   | 25.09.28 | 每日小米运动刷步数                                                           |
| 🟢️  | BAIDU     | [百度站点](https://ziyuan.baidu.com/site/index#/)          | 25.09.28 | 提交网站页面供百度收录                                                       |

> 检查日期沿用上游最后一次实测记录；本 fork 修复的服务见下方「与上游差异」。

## 💬 通知列表

- dingtalk（钉钉）
- 企业微信群机器人（企业微信）
- 企业微信应用消息（企业微信）
- telegram（TG）
- Bark（iOS）
- server 酱（微信）
- server 酱 TURBO（微信）
- pushplus（微信）
- Cool Push（QQ,微信,邮箱）
- qmsg 酱（QQ）
- 飞书（飞书）
- gotify（安卓）
- ntfy（安卓）
- wpush（微信）
- xxtui（微信）

## 🔀 与上游差异

本仓库 fork 自 [Sitoi/dailycheckin](https://github.com/Sitoi/dailycheckin)（基于上游 v25.12.9），致敬并感谢原作者 [Sitoi](https://github.com/sitoi) 与所有上游贡献者。

### 部署链

- Docker 镜像发布在 `ghcr.io/byterax/dailycheckin_plus`（amd64 + arm64），由本仓库源码构建，不依赖 PyPI。
- 镜像与部署脚本不再从 PyPI 自动升级，升级方式为拉取新镜像或重新执行源码安装。
- Release 工作流只构建 sdist + wheel 并附着在 GitHub Release，不发布 PyPI。

### 已吸收的上游 Issue / PR

| 类别 | 内容 | 来源 |
| ---- | ---- | ---- |
| 通知 | 新增 WPUSH 渠道 | #590 |
| 通知 | 新增 xxtui 渠道 | #564 |
| 通知 | qmsg 支持 qq/bot 参数与私有部署 URL | #566 #453 |
| 通知 | bark 支持 group/icon 参数并修复 URL query 拼接 | #387 #523 #320 |
| CLI | 新增 `--accounts` 按账号序号执行部分账号（重实现） | #544 #533 #565 |
| 签到 | bilibili 接口失效与假成功修复 | #588 #586 #585 #515 |
| 签到 | 恩山 WAF 521 融合修复 | #562 #572 #557 #569 #501 |
| 签到 | 百度网盘签到成功后原子回写续期 cookie | #591 #534 #577 |
| 签到 | 什么值得买奖励解析修复 | #479 #571 #523 |
| 签到 | V2EX 签到链接缺失时显式报错 | #525 |
| 签到 | 百度贴吧签到接口切换 | #509 |
| 签到 | 飞牛 NAS 登录失效检测 | #589 |
| 签到 | i 茅台门店接口 404 与假成功修复 | #563 #568 |

> 编号均指 [Sitoi/dailycheckin](https://github.com/Sitoi/dailycheckin) 的 Issue / PR，感谢上述所有作者。

### fork 更新方法

同步上游新提交（维护者视角）：

```bash copy
git remote add upstream https://github.com/Sitoi/dailycheckin.git # 首次添加
git fetch upstream
git merge upstream/main # 或 git rebase upstream/main
```

更新 Docker 部署（用户视角）：

```bash copy
docker pull ghcr.io/byterax/dailycheckin_plus:latest
docker-compose pull && docker-compose up -d # docker-compose 部署时
```

更新源码安装（用户视角）：

```bash copy
pip install --upgrade "dailycheckin @ git+https://github.com/ByteRax/dailycheckin_plus@main"
```

## 🤝 参与贡献

我们非常欢迎各种形式的贡献。如果你对贡献代码感兴趣，可以查看我们的 GitHub [Issues][github-issues-link]，大展身手，向我们展示你的奇思妙想。

[![][pr-welcome-shield]][pr-welcome-link]

### 💗 感谢我们的贡献者

上游贡献者（致敬）：

[![][github-contrib-shield]][github-contrib-link]

## ✨ Star 数

> Star 数展示上游 [Sitoi/dailycheckin](https://github.com/Sitoi/dailycheckin)，致敬原作者。

[![][starchart-shield]][starchart-link]

---

## 📝 License

Copyright © 2021 [Sitoi][profile-link]. <br />
This project is [MIT](https://github.com/ByteRax/dailycheckin_plus/blob/main/LICENSE) licensed.

<!-- LINK GROUP -->

[profile-link]: https://github.com/sitoi
[upstream-repo-link]: https://github.com/Sitoi/dailycheckin
[github-contributors-link]: https://github.com/ByteRax/dailycheckin_plus/graphs/contributors
[github-contributors-shield]: https://img.shields.io/github/contributors/ByteRax/dailycheckin_plus?color=c4f042&labelColor=black&style=flat-square
[github-forks-link]: https://github.com/ByteRax/dailycheckin_plus/network/members
[github-forks-shield]: https://img.shields.io/github/forks/ByteRax/dailycheckin_plus?color=8ae8ff&labelColor=black&style=flat-square
[github-issues-link]: https://github.com/ByteRax/dailycheckin_plus/issues
[github-issues-shield]: https://img.shields.io/github/issues/ByteRax/dailycheckin_plus?color=ff80eb&labelColor=black&style=flat-square
[github-license-link]: https://github.com/ByteRax/dailycheckin_plus/blob/main/LICENSE
[github-license-shield]: https://img.shields.io/github/license/ByteRax/dailycheckin_plus?labelColor=black&style=flat-square
[github-stars-link]: https://github.com/ByteRax/dailycheckin_plus/stargazers
[github-stars-shield]: https://img.shields.io/github/stars/ByteRax/dailycheckin_plus?color=ffcb47&labelColor=black&style=flat-square
[github-releases-link]: https://github.com/ByteRax/dailycheckin_plus/releases
[github-releases-shield]: https://img.shields.io/github/v/release/ByteRax/dailycheckin_plus?labelColor=black&style=flat-square
[github-release-date-link]: https://github.com/ByteRax/dailycheckin_plus/releases
[github-release-date-shield]: https://img.shields.io/github/release-date/ByteRax/dailycheckin_plus?labelColor=black&style=flat-square
[pr-welcome-link]: https://github.com/ByteRax/dailycheckin_plus/pulls
[pr-welcome-shield]: https://img.shields.io/badge/🤯_pr_welcome-%E2%86%92-ffcb47?labelColor=black&style=for-the-badge
[github-contrib-link]: https://github.com/Sitoi/dailycheckin/graphs/contributors
[github-contrib-shield]: https://contrib.rocks/image?repo=sitoi%2Fdailycheckin
[ghcr-shield]: https://img.shields.io/badge/ghcr.io-byterax%2Fdailycheckin_plus-2496ED?labelColor=black&style=flat-square&logo=github
[ghcr-link]: https://github.com/ByteRax/dailycheckin_plus/pkgs/container/dailycheckin_plus
[python-version-link]: #快速开始
[python-version-shield]: https://img.shields.io/badge/python-3.9%2B-3776AB?labelColor=black&style=flat-square&logo=python
[starchart-shield]: https://api.star-history.com/svg?repos=sitoi/dailycheckin&type=Date
[starchart-link]: https://star-history.com/#sitoi/dailycheckin&Date
