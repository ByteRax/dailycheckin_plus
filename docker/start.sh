#!/bin/sh
set -e

export LANG="zh_CN.UTF-8"

CRONTAB_FILE="/dailycheckin/cron/crontab_list.sh"

# fork 镜像固定源码版本，升级 = 拉新镜像（不再从 PyPI 自动升级上游包）

echo "加载最新的定时任务文件..."
crontab $CRONTAB_FILE

if [ $CRONTAB_FILE ]; then
  chmod -R 777 $CRONTAB_FILE
fi

echo "启动 crondtab 定时任务主进程..."
cron -f