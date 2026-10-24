# debian(slim) cron 的默认 PATH 不保证包含 /usr/local/bin（上游 alpine 镜像靠 /usr/bin 软链兜底），
# 显式声明 PATH 确保定时任务能解析到源码安装的 dailycheckin 入口
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

##############默认任务##############
# fork 镜像固定源码版本，升级 = 拉新镜像（原每 12 小时 PyPI 自动升级任务已移除）
# 每天的 23:50 分清理一次日志
50 23 */2 * * rm -rf /dailycheckin/logs/*.log

##############每日签到一次任务##############
# 每日签到(9:00 执行全部签到)
0 9 * * * cd /dailycheckin && dailycheckin >> /dailycheckin/logs/dailycheckin.log 2>&1
