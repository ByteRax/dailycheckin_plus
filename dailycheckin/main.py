import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone

from dailycheckin.__version__ import __version__
from dailycheckin.configs import checkin_map, get_checkin_info, get_notice_info
from dailycheckin.utils.message import push_message


def _to_account_index(value):
    try:
        index = int(value)
    except ValueError:
        raise ValueError(f"账号序号必须是正整数: {value!r}") from None
    if index < 1:
        raise ValueError(f"账号序号必须从 1 开始: {value!r}")
    return index


def _parse_accounts_spec(spec):
    """解析 --accounts 参数为 1-based 账号序号列表。

    语法: 逗号分隔, 支持单值与闭区间混用, 例如 "1,3-5"。
    返回去重后的升序序号列表; 输入为空、含非数字、序号小于 1、
    区间左界大于右界时抛出 ValueError。
    """
    indexes = set()
    for raw_token in str(spec).split(","):
        token = raw_token.strip()
        if not token:
            raise ValueError(f"账号序号格式错误: {spec!r}")
        parts = token.split("-")
        if len(parts) == 1:
            start = end = _to_account_index(parts[0])
        elif len(parts) == 2:
            start = _to_account_index(parts[0])
            end = _to_account_index(parts[1])
            if start > end:
                raise ValueError(f"区间左界不能大于右界: {token}")
        else:
            raise ValueError(f"账号序号格式错误: {token}")
        indexes.update(range(start, end + 1))
    return sorted(indexes)


def _accounts_spec_arg(value):
    try:
        return _parse_accounts_spec(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--include", nargs="+", help="任务执行包含的任务列表")
    parser.add_argument("--exclude", nargs="+", help="任务执行排除的任务列表")
    parser.add_argument(
        "--accounts",
        type=_accounts_spec_arg,
        help='账号序号选择，如 "1,3-5"（1-based 闭区间，逗号与范围可混用；'
        "对每个服务各自的账号列表独立生效，作用于 include/exclude 过滤之后）",
    )
    return parser.parse_args()


def _resolve_task_names(names):
    """按大小写不敏感方式把输入服务名匹配到注册表键, 返回 (匹配键列表, 未匹配输入列表)。"""
    matched, unmatched = [], []
    for one in names:
        key = one.upper()
        if key in checkin_map:
            matched.append(key)
        else:
            unmatched.append(one)
    return matched, unmatched


def _select_accounts(check_info, accounts_spec):
    """按 1-based 序号对每个服务的账号列表独立切片。

    返回新 dict, 值为 (原始 0-based 序号, 账号) 的列表;
    越界序号打警告并忽略, 切片后为空的服务提示跳过。
    """
    selected_info = {}
    for one_check, check_list in check_info.items():
        check_name = checkin_map.get(one_check.upper())[0]
        selected = [i for i in accounts_spec if i <= len(check_list)]
        out_of_range = [i for i in accounts_spec if i > len(check_list)]
        if out_of_range:
            print(
                f"警告: 「{check_name}」共 {len(check_list)} 个账号，序号 {','.join(map(str, out_of_range))} 超出范围，已忽略"
            )
        if not selected:
            print(f"「{check_name}」没有符合 --accounts 选择的账号，跳过该服务")
            continue
        selected_info[one_check] = [(i - 1, check_list[i - 1]) for i in selected]
    return selected_info


def _format_account_result(check_name, msg):
    """生成单账号结果的通知文案与成功标记; main() 返回 None 视为签到失败。"""
    if msg is None:
        return f"「{check_name}」\n签到失败（无返回结果）", False
    return f"「{check_name}」\n{msg}", True


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
                return False, False
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
            return notice_info, check_info
        except Exception as e:
            print(e)
            return False, False
    else:
        print("未找到 config.json 配置文件\n请在下方任意目录中添加「config.json」文件:\n" + "\n".join(config_path_list))
        return False, False


def checkin():
    start_time = time.time()
    utc_time = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    print(f"当前时间: {utc_time}\n当前版本: {__version__}")
    args = parse_arguments()
    available_names = ", ".join(sorted(checkin_map.keys()))
    if args.include:
        include, unknown = _resolve_task_names(args.include)
        if unknown:
            print(f"警告: --include 中未找到服务: {', '.join(unknown)}")
            print(f"可用服务: {available_names}")
    else:
        include = list(checkin_map.keys())
    if args.exclude:
        exclude, unknown = _resolve_task_names(args.exclude)
        if unknown:
            print(f"警告: --exclude 中未找到服务: {', '.join(unknown)}")
            print(f"可用服务: {available_names}")
    else:
        exclude = []
    task_list = list(set(include) - set(exclude))
    if not task_list:
        print("过滤后没有可执行的签到任务！")
        print(f"可用服务: {available_names}")
        return
    notice_info, check_info = check_config(task_list)
    if not check_info:
        print("没有可执行的签到任务！")
        return
    if args.accounts:
        check_info = _select_accounts(check_info, args.accounts)
        if not check_info:
            print("--accounts 选择后没有可执行的签到任务！")
            return
        indexed_info = check_info
    else:
        indexed_info = {one_check: list(enumerate(check_list)) for one_check, check_list in check_info.items()}
    task_name_str = "\n".join(
        [f"「{checkin_map.get(one.upper())[0]}」账号数 : {len(value)}" for one, value in indexed_info.items()]
    )
    print(f"\n---------- 本次执行签到任务如下 ----------\n\n{task_name_str}\n\n")
    content_list = []
    for one_check, indexed_accounts in indexed_info.items():
        check_name, check_func = checkin_map.get(one_check.upper())
        print(f"----------开始执行「{check_name}」签到----------")
        for index, check_item in indexed_accounts:
            try:
                msg = check_func(check_item).main()
                text, success = _format_account_result(check_name, msg)
                content_list.append(text)
                if success:
                    print(f"第 {index + 1} 个账号: ✅✅✅✅✅")
                else:
                    print(f"第 {index + 1} 个账号: ❌❌❌❌❌\n{text.splitlines()[-1]}")
            except Exception as e:
                content_list.append(f"「{check_name}」\n{e}")
                print(f"第 {index + 1} 个账号: ❌❌❌❌❌\n{e}")
    print("\n\n")
    # fork 不再检查上游 PyPI 版本：同名 PyPI 项目归上游所有，对比结果会误导用户装回上游包
    content_list.append(
        f"开始时间: {utc_time}\n"
        f"任务用时: {int(time.time() - start_time)} 秒\n"
        f"当前版本: {__version__}\n"
        f"项目地址: https://github.com/ByteRax/dailycheckin_plus"
    )
    push_message(content_list=content_list, notice_info=notice_info)
    return


if __name__ == "__main__":
    checkin()
