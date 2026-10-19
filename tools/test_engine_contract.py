#!/usr/bin/env python3
"""引擎对外契约的基线测试 —— 重构期间锁死「不可变的那部分」。

面板依赖引擎的一组约定，重构时**只能改实现、不能改这些**：

1. **站点 KEY 与类名**：``configs.checkin_map`` 用类名大写作 KEY，
   面板的 ``/api/state``、站点配置、校验状态全按它索引。
2. **中文名** ``name``：卡片上显示的站名。
3. **构造签名** ``Cls(check_item=<dict>)``：引擎按关键字传参。
4. **``main()`` 返回 str**：以 ``"标题: 值"`` 每行一条的文本，
   面板与通知都直接渲染它。
5. **缺失 cookie 时抛异常**：面板靠捕获异常把卡片标红。

改动这些会让既有配置失效，所以逐项断言。
跑法：python3 tools/test_engine_contract.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed, failed = [], []


def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(f"  [{'OK' if cond else 'FAIL]'}]   {name}" + (f":: {detail}" if not cond and detail else ""))


def section(title):
    print("\n" + "=" * 70)
    print(title)


# --------------------------------------------------------------------------- #
section("1) 站点清单：17 个，KEY / 类名 / 中文名")

from unicheckin.configs import checkin_map  # noqa: E402

# 重构前的快照，改动这里等于改了对外契约
BASELINE = {
    "ACFUN": ("AcFun", "AcFun"),
    "ALIYUN": ("AliYun", "阿里云盘"),
    "AOLAXING": ("AoLaXing", "奥拉星"),
    "BAIDU": ("Baidu", "百度站点提交"),
    "BAIDUWP": ("BaiduWP", "百度网盘"),
    "BILIBILI": ("BiliBili", "Bilibili"),
    "ENSHAN": ("EnShan", "恩山无线论坛"),
    "FNNASCLUB": ("FnNasClub", "飞牛Nas论坛"),
    "IMAOTAI": ("IMAOTAI", "i茅台"),
    "IQIYI": ("IQIYI", "爱奇艺"),
    "KGQQ": ("KGQQ", "全民K歌"),
    "MIMOTION": ("MiMotion", "小米运动"),
    "SMZDM": ("SMZDM", "什么值得买"),
    "TIEBA": ("Tieba", "百度贴吧"),
    "V2EX": ("V2ex", "V2EX 论坛"),
    "WEIBO": ("Weibo", "微博超话"),
    "YOUDAO": ("YouDao", "有道云笔记"),
}

check("站点数量是 17", len(checkin_map) == 17, f"实际 {len(checkin_map)}: {sorted(checkin_map)}")
check("站点 KEY 集合未变", set(checkin_map) == set(BASELINE),
      f"多: {sorted(set(checkin_map) - set(BASELINE))} 少: {sorted(set(BASELINE) - set(checkin_map))}")

for key in sorted(BASELINE):
    want_cls, want_name = BASELINE[key]
    got = checkin_map.get(key)
    if not got:
        check(f"{key} 存在", False, "checkin_map 里没有")
        continue
    label, cls = got
    check(f"{key:12} 类名={want_cls}", cls.__name__ == want_cls, f"实际 {cls.__name__}")
    check(f"{key:12} 中文名={want_name}", label == want_name, f"实际 {label!r}")
    check(f"{key:12} 构造签名接受 check_item 关键字", "check_item" in cls.__init__.__code__.co_varnames,
          str(cls.__init__.__code__.co_varnames[:6]))

# --------------------------------------------------------------------------- #
section("2) 统一入口：python -m unicheckin.main 的参数与行为")

import unicheckin.main as engine_main  # noqa: E402

check("有 parse_arguments()", hasattr(engine_main, "parse_arguments"))
check("有 checkin()", hasattr(engine_main, "checkin"))
check("有 check_config()", hasattr(engine_main, "check_config"))

# check_config 找不到配置文件时必须返回 (False, False) 而不是抛异常 ——
# 面板会先探测这一步来决定要不要提示「未配置」
check("check_config 是可调用函数", callable(engine_main.check_config))

# --------------------------------------------------------------------------- #
section("3) 缺 cookie / 空配置必须抛异常（面板据此标红）")

# 空 cookie 的站点必须以「抛异常」收场，绝不能静默返回成功文本 ——
# 面板把异常标红、静默成功标绿，这个差别决定了用户能否发现配置错了。
#
# 注：现状是 TIEBA / WEIBO 在构造期抛 ValueError，而 V2EX 要到 main() 里
# 才抛（IndexError）。重构时统一成构造期抛错，这里先按现状断言。
for key, item, stage in (
    ("TIEBA", {"cookie": ""}, "构造期"),
    ("WEIBO", {}, "构造期"),
    ("V2EX", {"cookie": ""}, "main()"),
):
    _, cls = checkin_map[key]
    raised = ""
    try:
        obj = cls(check_item=item)
        if stage == "main()":
            obj.main()
    except Exception as exc:  # noqa: BLE001
        raised = type(exc).__name__
    check(f"{key} 空 cookie 在{stage}抛异常", bool(raised), "没抛 —— 面板会误判为有效")

# --------------------------------------------------------------------------- #
section("4) main() 的返回值必须是 str 且不是 None")

# 只验证「不崩溃 + 返回类型」，不发真实网络请求：
# 用一个必然失败的代理让请求立即出错，走except 分支。
import os as _os  # noqa: E402

# 走不通的网络下 main() 要么抛异常、要么返回 str 文本，**绝不能返回 None** ——
# 面板与通知都直接把它当字符串渲染，None 会让输出变成 "None"。
for key in ("V2EX", "WEIBO"):
    _, cls = checkin_map[key]
    obj = cls(check_item={"cookie": "SUB=x; SUBP=y", "proxy": "http://127.0.0.1:1"})
    out = "<raised>"
    try:
        out = obj.main()
    except Exception:  # noqa: BLE001
        out = "<raised>"
    ok = (out == "<raised>") or isinstance(out, str)
    check(f"{key} main() 返回 str 或抛异常（不会返回 None）", ok, f"实际 {type(out).__name__}: {out!r:.40}")

# --------------------------------------------------------------------------- #
section("5) configs 的通知渠道键集合未变")

from unicheckin.configs import notice_map  # noqa: E402

# 面板与用户的 config.json 里按这些小写键取通知配置，删一个就少一种通知方式
EXPECT_NOTICE = {
    "bark_url", "coolpushemail", "coolpushqq", "coolpushskey", "coolpushwx",
    "dingtalk_access_token", "dingtalk_secret", "fskey",
    "pushplus_token", "pushplus_topic",
    "qmsg_key", "qmsg_type",
    "qywx_agentid", "qywx_corpid", "qywx_corpsecret", "qywx_key", "qywx_touser",
    "qywx_media_id", "qywx_origin",
    "sckey", "sendkey",
    "tg_api_host", "tg_bot_token", "tg_proxy", "tg_user_id",
    "merge_push",
    "gotify_url", "gotify_token", "gotify_priority",
    "ntfy_url", "ntfy_topic", "ntfy_priority",
}
got_notice = {k.lower() for k in notice_map}
check("通知渠道键集合未变", got_notice == EXPECT_NOTICE,
      f"多: {sorted(got_notice - EXPECT_NOTICE)} 少: {sorted(EXPECT_NOTICE - got_notice)}")

# --------------------------------------------------------------------------- #
section("6) 站点目录结构：每个站点目录都要有 __init__.py 与 main.py")

import glob  # noqa: E402

for key in sorted(BASELINE):
    d = os.path.join(ROOT, "unicheckin", key.lower())
    check(f"{key.lower()}/ 有 __init__.py", os.path.isfile(os.path.join(d, "__init__.py")))
    check(f"{key.lower()}/ 有 main.py", os.path.isfile(os.path.join(d, "main.py")))

# --------------------------------------------------------------------------- #
print("\n" + "=" * 70)
print(f"通过 {len(passed)} 项，失败 {len(failed)} 项")
if failed:
    print("\n失败项：")
    for one in failed:
        print("  - " + one)
sys.exit(1 if failed else 0)