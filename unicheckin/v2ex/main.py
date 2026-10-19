"""V2EX 每日登录奖励。

流程：抓签到按钮 -> 跟着它给的地址领奖励 -> 回余额页取余额与连续天数。

页面结构是 Discuz 那套，靠正则从 HTML 里抠数据。接口若改版，
最可能的表现是「正则匹配不到」，所以每一处都给了兜底文案 ——
宁可显示「获取失败」，也不要让 KeyError 冒上去把整条结果吞掉。
"""

import re

from unicheckin import MOBILE_UA, CheckIn, CheckInError, Result

BASE = "https://www.v2ex.com"

# 签到按钮长这样：
#   <input ... onclick="location.href = '/mission/daily/donate?once=xxxx';" />
# once 后面那串是一次性令牌，必须原样带回去。
#
# 只锚定 location.href = '...' 而不写整条标签：onclick 的值里含 '>'，
# 用 `<input[^>]*onclick=` 会因为 [^>] 撞上它而匹配失败；而且属性顺序一变就失效。
_BUTTON_RE = re.compile(r"""location\.href\s*=\s*['"](?P<url>[^'"]+)['"]""")

_USERNAME_RE = re.compile(r'href="/member/[^"/]+"[^>]*class="top">([^<]+)</')
_BALANCE_RE = re.compile(r'<td class="d" style="text-align: right;">([\d.]+)</td>')
_TODAY_RE = re.compile(r'<td class="d"><span class="gray">([^<]*)</span></td>')
# 连续天数。页面里数字与「天」之间可能有空格（"30 天" 或 "30天"），
# 用 \s* 兼容；原来的正则只认后者，站点加个空格就取不到值。
_STREAK_RE = re.compile(r'<div class="cell">\s*(\d+)\s*天\s*</div>')


def _first(pattern, text, default="获取失败"):
    """取正则的第一个捕获组，没有就返回 default。

    不写死组名（有的正则叫 ``v`` 有的叫 ``name``）——取第一个非命名组即可，
    加个命名组纯粹是给人看的，写它只是给自己制造不一致的机会。
    """
    m = pattern.search(text)
    if not m:
        return default
    try:
        value = m.group(1)
    except IndexError:
        return default
    return value.strip() or default


class V2ex(CheckIn):
    name = "V2EX 论坛"
    base_url = BASE
    user_agent = MOBILE_UA

    def run(self) -> Result:
        self.require_cookie("A2")
        http = self.http(verify=False)  # V2EX 证书链在部分容器里验不过
        result = Result()

        page = http.text("GET", self.url("/mission/daily"))
        m = _BUTTON_RE.search(page)
        if not m:
            # 页面结构变了，或者 cookie 已经失效跳到登录页 —— 两种都归为拿不到按钮
            raise CheckInError("没找到签到按钮，cookie 可能已过期")

        target = m.group("url")
        # 已经领过的页面会直接给 /balance，那就不用再点了
        if target != "/balance":
            http.get(self.url(target), params={"once": target.rsplit("=", 1)[-1]},
                     headers={"Referer": self.url("/mission/daily")})

        balance_page = http.text("GET", self.url("/balance"))
        result.add("帐号信息", _first(_USERNAME_RE, balance_page, "用户名获取失败"))
        result.add("今日签到", _first(_TODAY_RE, balance_page))
        result.add("帐号余额", _first(_BALANCE_RE, balance_page))

        daily = http.text("GET", self.url("/mission/daily"))
        streak = _STREAK_RE.search(daily)
        result.add("签到天数", f"{streak.group(1)}天" if streak else "获取连续签到天数失败")
        return result