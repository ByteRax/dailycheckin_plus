#!/bin/sh
set -e

export LANG="zh_CN.UTF-8"

# fork 镜像固定源码版本，升级 = 拉新镜像（不再从 PyPI 自动升级上游包）

echo "Load the latest crontab task file..."
echo "加载最新的定时任务文件..."
crontab /dailycheckin/cron/crontab_list.sh
