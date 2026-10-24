"""基线特征测试:服务注册表 checkin_map。

锁定 `import dailycheckin` 后的注册结果:16 个服务,值为 (显示名, 类) 二元组。
对应实现:dailycheckin/__init__.py(pkgutil 自动发现)与 dailycheckin/configs.py 的 checkin_map。
"""

import dailycheckin
from dailycheckin import CheckIn
from dailycheckin.configs import checkin_map

EXPECTED_SERVICES = {
    "ACFUN": "AcFun",
    "ALIYUN": "阿里云盘",
    "AOLAXING": "奥拉星",
    "BAIDU": "百度站点提交",
    "BAIDUWP": "百度网盘",
    "BILIBILI": "Bilibili",
    "ENSHAN": "恩山无线论坛",
    "FNNASCLUB": "飞牛Nas论坛",
    "IMAOTAI": "i茅台",
    "IQIYI": "爱奇艺",
    "KGQQ": "全民K歌",
    "MIMOTION": "小米运动",
    "SMZDM": "什么值得买",
    "TIEBA": "百度贴吧",
    "V2EX": "V2EX 论坛",
    "YOUDAO": "有道云笔记",
}


def test_import_dailycheckin_registers_16_services():
    assert isinstance(checkin_map, dict)
    assert len(checkin_map) == 16


def test_checkin_map_covers_expected_keys():
    assert set(checkin_map.keys()) == set(EXPECTED_SERVICES.keys())


def test_checkin_map_value_is_display_name_and_class():
    for key, value in checkin_map.items():
        assert isinstance(value, tuple), key
        assert len(value) == 2, key
        display_name, cls = value
        assert isinstance(display_name, str), key
        assert isinstance(cls, type), key
        assert issubclass(cls, CheckIn), key
        assert value == (cls.name, cls), key


def test_checkin_map_display_names():
    for key, display_name in EXPECTED_SERVICES.items():
        assert checkin_map[key][0] == display_name, key


def test_registered_classes_are_direct_checkin_subclasses():
    subclasses = CheckIn.__subclasses__()
    assert {cls.__name__.upper() for cls in subclasses} == set(EXPECTED_SERVICES.keys())


def test_imported_package_is_worktree_source():
    # 可编辑安装（.venv-test -e .）后，dailycheckin 必须来自本仓库源码目录
    assert dailycheckin.__file__.endswith("dailycheckin/__init__.py")
    assert "/dailycheckin/" in dailycheckin.__file__
