#!/usr/bin/env python3
"""站点模块的行为测试（离线，不发真实网络请求）。

每个站点跑两件事：

1. **构造与配置校验** —— 缺必填 cookie 时必须抛 ``ConfigError``，
   不能静默成功（面板靠这个把卡片标红）
2. **解析逻辑** —— 打桩一份构造好的响应，验证 ``run()`` 提取的字段正确

不测「真实接口能不能通」：那是网络与对方站点的事，会让测试变得不稳定。
这里锁的是**我们自己的解析代码**——接口改版时真正会坏掉的那部分。

跑法：python3 tools/test_site_behavior.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from unicheckin import CheckIn, ConfigError  # noqa: E402
from unicheckin.configs import checkin_map  # noqa: E402

passed, failed = [], []


def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(f"  [{'OK' if cond else 'FAIL]'}]   {name}" + (f":: {detail}" if not cond and detail else ""))


def section(title):
    print("\n" + "=" * 70)
    print(title)


# --------------------------------------------------------------------------- #
# 打桩用的最小 HttpSession 替身：只实现站点模块用到的那几个方法
# --------------------------------------------------------------------------- #
class FakeResp:
    def __init__(self, text="", data=None, cookies=None, status=200):
        self.text = text
        self._data = data or {}
        self.cookies = cookies or {}
        self.status_code = status

    def json(self):
        return self._data


class FakeHttp:
    """按 (方法, URL) 或 URL 返回预设响应，并记录调用顺序。"""

    def __init__(self, routes=None):
        # routes: {(method, url): FakeResp | dict | str}；未命中时返回空响应
        self.routes = routes or {}
        self.calls = []
        self.replaced_cookies = None

    def _key(self, method, url):
        return (method.upper(), url)

    def _resolve(self, method, url):
        """依次尝试 (方法, URL)、(None, URL)、纯字符串三种写法。

        站点模块调 text/json 时传的 URL 常常带或不带查询串
        （``self.url(path)`` 与 ``self.url(path) + "?x=1"`` 并存），
        所以 URL 匹配再按前缀兜底一次，免得每写一个用例都得把完整 URL 拼对。
        """
        for key in ((method.upper(), url), (None, url), (url,)):
            if key in self.routes:
                return self.routes[key]
        for key, value in self.routes.items():
            if not isinstance(key, tuple):
                if isinstance(key, str) and key and url.startswith(key):
                    return value
                continue
            m, route_url = key[0], key[1]
            if isinstance(route_url, str) and route_url and url.startswith(route_url):
                if m in (None, method.upper()):
                    return value
        return FakeResp()

    def request(self, method, url, **kwargs):
        self.calls.append((method.upper(), url))
        value = self._resolve(method, url)
        if isinstance(value, FakeResp):
            return value
        if isinstance(value, dict):
            return FakeResp(data=value)
        return FakeResp(text=str(value))

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def text(self, method, url, **kwargs):
        self.calls.append((method.upper(), url))
        value = self._resolve(method, url)
        return value.text if isinstance(value, FakeResp) else str(value)

    def json(self, method, url, **kwargs):
        self.calls.append((method.upper(), url))
        value = self._resolve(method, url)
        if isinstance(value, FakeResp):
            return value._data
        return value if isinstance(value, dict) else {}

    def replace_cookies(self, jar):
        self.replaced_cookies = jar
        return self

    def adopt_cookies(self, resp):
        return self

    @property
    def session(self):
        return self  # 让误用 requests 内部结构的代码在这里就暴露


def build(key, item, routes=None):
    """构造站点对象并注入打桩会话。"""
    _, cls = checkin_map[key]
    obj = cls(check_item=item)
    if routes is not None:
        obj._session = FakeHttp(routes)
    return obj


# --------------------------------------------------------------------------- #
section("1) V2EX —— HTML 正则解析")

V2EX_DAILY = (
    '<input type="button" class="super normal button" value="签到" '
    "onclick=\"location.href = '/mission/daily/donate?once=TOKEN123';\" />"
    '<div class="cell">30 天</div>'
)
V2EX_BALANCE = (
    '<a href="/member/abc" class="top">myuser</a>'
    '<td class="d"><span class="gray">20261019</span></td>'
    '<td class="d" style="text-align: right;">123.45</td>'
)

obj = build("V2EX", {"cookie": "A2=abc"}, {
    "https://www.v2ex.com/mission/daily": V2EX_DAILY,
    "https://www.v2ex.com/balance": V2EX_BALANCE,
})
out = obj.main()
check("抽出用户名", "帐号信息: myuser" in out, out)
check("抽出今日签到", "今日签到: 20261019" in out, out)
check("抽出余额", "帐号余额: 123.45" in out, out)
check("抽出连续天数（数字与「天」间有空格也能解析）", "签到天数: 30天" in out, out)
check("每行都是「标题: 值」", all(":" in ln for ln in out.splitlines()), out)

obj = build("V2EX", {"cookie": "A2=abc"}, {
    "https://www.v2ex.com/mission/daily": "<html>登录页</html>",
})
try:
    obj.run()
    check("页面没有按钮时抛异常", False, "居然没抛")
except Exception as exc:  # noqa: BLE001
    check("页面没有按钮时抛异常（不静默成功）", True)
    check("异常文案提到 cookie 可能过期", "cookie" in str(exc).lower(), str(exc))

# 正则不能因为 onclick 值里含 '>' 就失效（这是重写时踩过的坑）
obj = build("V2EX", {"cookie": "A2=abc"}, {
    "https://www.v2ex.com/mission/daily":
        '<input onclick="location.href = \'/mission/daily/donate?once=T\' >" />',
})
try:
    obj.run()
    check("onclick 内含 > 时正则仍能匹配", True)
except Exception as exc:  # noqa: BLE001
    check("onclick 内含 > 时正则仍能匹配", False, str(exc))

# --------------------------------------------------------------------------- #
section("2) 有道云笔记 —— 多接口串联 + 空间累加")

MB = 1024 * 1024
obj = build("YOUDAO", {"cookie": "YNOTE_PERS=app||myuid||tok"}, {
    "https://note.youdao.com/login/acc/pe/getsess": FakeResp(cookies={"YNOTE_SESS": "fresh"}),
    "https://note.youdao.com/yws/api/daupromotion": {"rewardSpace": 3 * MB},
    "https://note.youdao.com/yws/mapi/user": {"space": 2 * MB},
})
out = obj.main()
check("从 YNOTE_PERS 抽出 uid", "帐号信息: myuid" in out, out)
check("三处空间相加（sync 3 + checkin 2 + 广告 3轮×2 = 11）", "+11M" in out, out)
check("已把 session cookie 换掉", obj._session.replaced_cookies == {"YNOTE_SESS": "fresh"},
      str(obj._session.replaced_cookies))

obj = build("YOUDAO", {"cookie": "YNOTE_PERS=app||myuid||tok"}, {
    "https://note.youdao.com/yws/api/daupromotion": {"error": "AUTHENTICATION_FAILURE"},
})
try:
    obj.run()
    check("接口回 error 时抛异常", False, "居然没抛")
except Exception as exc:  # noqa: BLE001
    check("接口回 error 时抛异常（不静默成功）", True)
    check("异常提示 cookie 过期", "ookie" in str(exc), str(exc))

# --------------------------------------------------------------------------- #
section("3) 配置校验：缺必填 cookie 必须抛 ConfigError")

CASES = [
    ("V2EX", {"cookie": "A2=abc"}, {"cookie": "OTHER=1"}, "A2"),
    ("YOUDAO", {"cookie": "YNOTE_PERS=a||b||c"}, {"cookie": "X=1"}, "YNOTE_PERS"),
]
for key, good, bad, field in CASES:
    _, cls = checkin_map[key]
    raised = None
    try:
        cls(check_item=bad).run()
    except ConfigError as exc:
        raised = str(exc)
    except Exception as exc:  # noqa: BLE001
        raised = f"WRONG_TYPE:{type(exc).__name__}"
    check(f"{key} 缺 {field} 时抛 ConfigError", raised is not None and not raised.startswith("WRONG_TYPE"),
          raised or "没抛")
    if raised and not raised.startswith("WRONG_TYPE"):
        check(f"{key} 异常文案点名 {field}", field in raised, raised)

# 空 cookie 也一样
for key in ("V2EX", "YOUDAO"):
    _, cls = checkin_map[key]
    try:
        cls(check_item={"cookie": ""}).run()
        check(f"{key} 空 cookie 抛异常", False, "没抛")
    except Exception:  # noqa: BLE001
        check(f"{key} 空 cookie 抛异常", True)

# --------------------------------------------------------------------------- #
section("4) 基类设施")

from unicheckin import parse_cookie  # noqa: E402

check("cookie 用 ; 无空格也能解析", parse_cookie("A=1;B=2") == {"A": "1", "B": "2"})
check("cookie 用换行也能解析", parse_cookie("A=1\nB=2") == {"A": "1", "B": "2"})
check("值里的 = 不被截断",
      parse_cookie("SUB=_2A25abc==")["SUB"] == "_2A25abc==",
      parse_cookie("SUB=_2A25abc==").get("SUB", ""))
check("无法解析的片段被跳过", parse_cookie("A=1; junk; B=2") == {"A": "1", "B": "2"})
check("空串返回空字典", parse_cookie("") == {})
check("字典原样返回", parse_cookie({"a": "1"}) == {"a": "1"})

from unicheckin import Result  # noqa: E402

r = Result()
r.add("标题", "值").add("空值", None)
check("Result 渲染成「标题: 值」", r.render() == "标题: 值\n空值: —", r.render())
r2 = Result()
r2.flag("成功项", True, "已完成")
r2.flag("失败项", False, "出错")
check("flag 加 ✅/❌ 前缀", "✅ 已完成" in r2.render() and "❌ 出错" in r2.render(), r2.render())
check("空 Result 布尔为假", bool(Result()) is False)
check("空 Result 渲染为空串", Result().render() == "")

# 基类 url() 拼地址
class _Demo(CheckIn):
    name = "demo"
    base_url = "https://demo.test"


d = _Demo(check_item={})
check("url 补全相对路径", d.url("/api/x") == "https://demo.test/api/x", d.url("/api/x"))
check("url 补全去掉多余斜杠", d.url("api/x") == "https://demo.test/api/x", d.url("api/x"))
check("url 不动绝对地址", d.url("https://other/y") == "https://other/y")

# 选项读取
d2 = _Demo(check_item={"n": "42", "flag": "yes", "blank": ""})
check("option_int 转换", d2.option_int("n", 0) == 42)
check("option_int 兜底默认值", d2.option_int("missing", 7) == 7)
check("option_int 非法值兜底", d2.option_int("blank", 3) == 3)
check("option_bool 识别 yes", d2.option_bool("flag", False) is True)
check("option 空串取默认", d2.option("blank", "dflt") == "dflt")


# --------------------------------------------------------------------------- #
section("5) 阿里云盘 —— 签到记录里取当天奖励")

from unicheckin.aliyun.main import AliYun  # noqa: E402

# signInLogs 倒序，[0] 是今天（status=miss 表示待签），它前面那条才是今天已签的记录
ALIYUN_CASES = [
    ("miss 在下标1，今天那条有奖励",
     {"signInCount": 5, "signInLogs": [
         {"status": "done", "isReward": True, "reward": {"name": "1G", "description": "流量"}},
         {"status": "miss"}]},
     True, "1G流量"),
    ("miss 在下标1，今天那条无奖励",
     {"signInCount": 5, "signInLogs": [
         {"status": "done", "isReward": False}, {"status": "miss"}]},
     False, ""),
    ("miss 在下标0（没有今天的历史）",
     {"signInCount": 5, "signInLogs": [{"status": "miss"}]},
     False, ""),
    ("没有 miss 条目",
     {"signInCount": 5, "signInLogs": [{"status": "done", "isReward": True}]},
     False, ""),
]
for label, inner, want_reward, want_text in ALIYUN_CASES:
    got_r = AliYun._today_reward(inner)
    got_t = AliYun._reward_text(inner)
    check(f"阿里云盘 {label}", got_r == want_reward and got_t == want_text,
          f"reward={got_r} text={got_t!r}")

# token 失效时必须抛异常 —— 原实现返回的是列表，会被渲染成 Python 字面量
obj = build("ALIYUN", {"refresh_token": ""})
try:
    obj.run()
    check("阿里云盘缺 refresh_token 时抛异常", False, "没抛")
except Exception:  # noqa: BLE001
    check("阿里云盘缺 refresh_token 时抛异常（不返回列表）", True)

obj = build("ALIYUN", {"refresh_token": "rt"}, {
    "https://auth.aliyundrive.com/v2/account/token": {"code": "RefreshTokenExpired", "message": "过期"},
})
try:
    obj.run()
    check("阿里云盘 token 失效时抛异常", False, "没抛")
except Exception as exc:  # noqa: BLE001
    check("阿里云盘 token 失效时抛异常（不返回列表）", True)
    check("异常文案带出接口的 message", "过期" in str(exc), str(exc))

# --------------------------------------------------------------------------- #
section("6) 百度站点提交 —— 配置校验与站点名提取")

from unicheckin.baidu.main import Baidu  # noqa: E402

check("从提交地址取出 site",
      Baidu._site_of("https://data.zz.baidu.com/urls?site=example.com&token=x") == "example.com")
check("site 缺失时给占位符",
      Baidu._site_of("https://data.zz.baidu.com/urls") == "—")

for item, label in (({}, "两个都缺"), ({"data_url": "u"}, "缺提交地址")):
    try:
        build("BAIDU", item).run()
        check(f"百度 {label} 时抛异常", False, "没抛")
    except ConfigError:
        check(f"百度 {label} 时抛 ConfigError", True)

# 提交次数与统计
obj = build("BAIDU", {
    "data_url": "https://example.com/sitemap.xml",
    "submit_url": "https://data.zz.baidu.com/urls?site=example.com&token=t",
    "times": 3,
}, {
    "https://example.com/sitemap.xml": "<urlset/>",
    "https://data.zz.baidu.com/urls": {"success": 2, "remain": 98},
})
out = obj.main()
check("百度 站点地址显示", "站点地址: example.com" in out, out)
check("百度 成功条数累计", "成功条数: 6" in out, out)
check("百度 成功次数", "成功次数: 3" in out, out)
check("百度 失败次数为 0", "失败次数: 0" in out, out)

# 提交失败要被计入失败次数而不是抛异常
obj = build("BAIDU", {
    "data_url": "https://example.com/sitemap.xml",
    "submit_url": "https://data.zz.baidu.com/urls?site=example.com",
    "times": 2,
}, {
    "https://example.com/sitemap.xml": "<urlset/>",
    "https://data.zz.baidu.com/urls": {},
})
out = obj.main()
check("全部失败时计入失败次数", "失败次数: 2" in out, out)
check("全部失败时成功次数为 0", "成功次数: 0" in out, out)
check("拿不到 remain 时用占位符", "剩余条数: —" in out, out)

# --------------------------------------------------------------------------- #
section("7) 奥拉星 —— 任务统计与积分")

obj = build("AOLAXING", {"cookie": "BT_LOGIN_tt_common=abc"}, {
    "http://service.100bt.com/creditmall/activity/daily_task_list.jsonp": {
        "jsonResult": {"data": [
            {"name": "登录", "status_desc": "已完成", "taskID": 1},
            {"name": "战斗", "status_desc": "已完成", "taskID": 2},
            {"name": "日常", "status_desc": "未完成", "taskID": 3},
        ]},
    },
    "http://service.100bt.com/creditmall/activity/do_task.jsonp": {"jsonResult": {"message": "OK"}},
    "http://service.100bt.com/creditmall/my/user_info.jsonp": {
        "jsonResult": {"data": {"credit": 100, "creditHistory": 2000,
                                "phoneNum": "13800000000", "signInTotal": 30}},
    },
})
out = obj.main()
check("奥拉星 任务总数", "今日任务总数: 3" in out, out)
check("奥拉星 已完成数", "今日任务完成数: 2" in out, out)
check("奥拉星 当前积分", "当前积分: 100" in out, out)
check("奥拉星 总签到", "总签到: 30" in out, out)

# 用户信息拿不到时要说明，不能崩
obj = build("AOLAXING", {"cookie": "BT_LOGIN_tt_common=abc"}, {
    "http://service.100bt.com/creditmall/activity/daily_task_list.jsonp": {"jsonResult": {"data": []}},
    "http://service.100bt.com/creditmall/my/user_info.jsonp": {},
})
out = obj.main()
check("用户信息缺失时给出提示而非崩溃", "获取用户信息失败" in out, out)

# --------------------------------------------------------------------------- #
section("8) 全民K歌 —— 必需cookie 与资料解析")

obj = build("KGQQ", {"cookie": "uid=123; openid=x; openkey=y"}, {
    "https://node.kg.qq.com/webapp/proxy": {
        "data": {"profile.getProfile": {"uFlowerNum": 100,
                                       "stPersonInfo": {"sKgNick": "歌神"}}},
    },
})
out = obj.main()
check("KGQQ 抽出昵称", "帐号信息: 歌神" in out, out)
check("KGQQ 报告当前鲜花", "当前鲜花: 100" in out, out)

try:
    build("KGQQ", {"cookie": "openid=x; openkey=y"}).run()
    check("KGQQ 缺 uid 时抛 ConfigError", False, "没抛")
except ConfigError as exc:
    check("KGQQ 缺 uid 时抛 ConfigError", True)
    check("KGQQ 异常文案点名 uid", "uid" in str(exc), str(exc))

# VIP 状态解析
obj = build("KGQQ", {"cookie": "uid=123"}, {
    "https://node.kg.qq.com/webapp/proxy": {
        "data": {
            "profile.getProfile": {"uFlowerNum": 50, "stPersonInfo": {"sKgNick": "n"}},
            "vip.get_vip_info": {"stVipCoreInfo": {"uStatus": 0}},
        },
    },
})
check("非 VIP 有明确文案", "非 VIP 用户" in obj.main(), obj.main())

# --------------------------------------------------------------------------- #
print("\n" + "=" * 70)
print(f"通过 {len(passed)} 项，失败 {len(failed)} 项")
if failed:
    print("\n失败项：")
    for one in failed:
        print("  - " + one)
sys.exit(1 if failed else 0)