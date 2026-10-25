import argparse
import json
import os
import re
import time
from datetime import datetime, timedelta

import requests

from dailycheckin.__version__ import __version__
from dailycheckin.configs import checkin_map, get_checkin_info, get_notice_info
from dailycheckin.utils.message import push_message


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--include", nargs="+", help="任务执行包含的任务列表")
    parser.add_argument("--exclude", nargs="+", help="任务执行排除的任务列表")
    parser.add_argument("--accounts", help="账号索引范围, 格式: start-end (闭区间, 例如: 0-1 表示运行前两个账号)")
    return parser.parse_args()


def parse_account_range(account_range):
    """解析账号范围参数, 返回 (start, end) 闭区间; 非法输入返回 None。"""
    if not account_range:
        return None
    match = re.fullmatch(r"(\d+)-(\d+)", str(account_range).strip())
    if not match:
        print(f"账号范围格式错误: {account_range}，应为 start-end (例如: 0-1)")
        return None
    start, end = int(match.group(1)), int(match.group(2))
    if start > end:
        print(f"账号范围无效: {account_range}，start 不能大于 end")
        return None
    return start, end


def check_config(task_list):
    config_path = None
    config_path_list = []
    for one_path in [
        "/ql/scripts/config.json",
        "config.json",
        "../config.json",
        "./config/config.json",
        "../config/config.json",
        "/config.json",
    ]:
        _config_path = os.path.join(os.getcwd(), one_path)
        if os.path.exists(_config_path):
            config_path = os.path.normpath(_config_path)
            break
        config_path_list.append(os.path.normpath(os.path.dirname(_config_path)))
    if config_path:
        print("使用配置文件路径:", config_path)
        with open(config_path, encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception:
                print("Json 格式错误，请检查 config.json 文件格式是否正确！")
                return False, False, config_path, None
        try:
            notice_info = get_notice_info(data=data)
            _check_info = get_checkin_info(data=data)
            check_info = {}
            for one_check in checkin_map.keys():
                if one_check in task_list:
                    if _check_info.get(one_check.lower()):
                        for _, check_item in enumerate(_check_info.get(one_check.lower(), [])):
                            if "xxxxxx" not in str(check_item) and "多账号" not in str(check_item):
                                if one_check.lower() not in check_info.keys():
                                    check_info[one_check.lower()] = []
                                check_info[one_check.lower()].append(check_item)
            return notice_info, check_info, config_path, data
        except Exception as e:
            print(e)
            return False, False, config_path, data
    else:
        print("未找到 config.json 配置文件\n请在下方任意目录中添加「config.json」文件:\n" + "\n".join(config_path_list))
        return False, False, None, None


def save_config(config_path, data) -> bool:
    """原子写回 config.json (保存服务运行中刷新的凭据), 保留原文件权限。"""
    temp_path = f"{config_path}.tmp"
    try:
        # 以原文件权限创建临时文件, 避免含凭据内容短暂暴露为全局可读
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, os.stat(config_path).st_mode & 0o777)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(temp_path, config_path)
        return True
    except Exception as e:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        print(f"更新 config.json 失败: {e}")
        return False


def checkin():
    start_time = time.time()
    utc_time = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    print(f"当前时间: {utc_time}\n当前版本: {__version__}")
    args = parse_arguments()
    include = args.include
    exclude = args.exclude
    account_range = parse_account_range(getattr(args, "accounts", None))
    if not include:
        include = list(checkin_map.keys())
    else:
        include = [one for one in include if one in checkin_map.keys()]
    if not exclude:
        exclude = []
    else:
        exclude = [one for one in exclude if one in checkin_map.keys()]
    task_list = list(set(include) - set(exclude))
    notice_info, check_info, config_path, config_data = check_config(task_list)
    if check_info:
        task_name_str = "\n".join(
            [f"「{checkin_map.get(one.upper())[0]}」账号数 : {len(value)}" for one, value in check_info.items()]
        )
        print(f"\n---------- 本次执行签到任务如下 ----------\n\n{task_name_str}\n\n")
        content_list = []
        for one_check, all_accounts in check_info.items():
            check_name, check_func = checkin_map.get(one_check.upper())
            print(f"----------开始执行「{check_name}」签到----------")
            check_list = all_accounts
            if account_range:
                start, end = account_range
                if start >= len(all_accounts):
                    print(f"账号范围起始 {start} 超出「{check_name}」账号数 {len(all_accounts)}，本服务不执行任何账号")
                    continue
                if end >= len(all_accounts):
                    print(f"账号范围 {start}-{end} 超出「{check_name}」账号数 {len(all_accounts)}，仅执行到末尾")
                check_list = all_accounts[start : end + 1]
            for index, check_item in enumerate(check_list):
                try:
                    check_item_before = json.dumps(check_item, ensure_ascii=False, sort_keys=True)
                except Exception:
                    check_item_before = None
                try:
                    msg = check_func(check_item).main()
                    content_list.append(f"「{check_name}」\n{msg}")
                    print(f"第 {index + 1} 个账号: ✅✅✅✅✅")
                except Exception as e:
                    content_list.append(f"「{check_name}」\n{e}")
                    print(f"第 {index + 1} 个账号: ❌❌❌❌❌\n{e}")
                finally:
                    try:
                        check_item_after = json.dumps(check_item, ensure_ascii=False, sort_keys=True)
                    except Exception:
                        check_item_after = None
                    if (
                        check_item_before is not None
                        and check_item_after != check_item_before
                        and config_path
                        and isinstance(config_data, dict)
                    ):
                        if save_config(config_path, config_data):
                            print("已将服务端刷新的凭据写回 config.json")
        print("\n\n")
        try:
            url = "https://pypi.org/pypi/dailycheckin/json"
            latest_version = requests.get(url=url, timeout=30).json()["info"]["version"]
        except Exception:
            print("获取最新版本失败")
            latest_version = "0.0.0"
        content_list.append(
            f"开始时间: {utc_time}\n"
            f"任务用时: {int(time.time() - start_time)} 秒\n"
            f"当前版本: {__version__}\n"
            f"最新版本: {latest_version}\n"
            f"项目地址: https://github.com/Sitoi/dailycheckin"
        )
        push_message(content_list=content_list, notice_info=notice_info)
        return


if __name__ == "__main__":
    checkin()
