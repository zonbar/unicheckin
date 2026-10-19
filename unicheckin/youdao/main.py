"""有道云笔记签到，顺带算一下空间增长。

接口要按顺序打：先刷新会话拿新 cookie，再用它同步、签到、领广告奖励，
最后把三处的空间增量加起来。少了任何一步都拿不到完整数值。
"""

from unicheckin import CheckIn, CheckInError, Result

MB = 1024 * 1024

# 空间以字节计，广告奖励要刷 3 次才满
AD_ROUNDS = 3

SYNC_API = "/yws/api/daupromotion"
USER_API = "/yws/mapi/user"
REFRESH_API = "/login/acc/pe/getsess"


class YouDao(CheckIn):
    name = "有道云笔记"
    base_url = "https://note.youdao.com"

    def run(self) -> Result:
        # YNOTE_PERS 里夹着用户 id，格式固定是 "appid||uid||token"
        ynote_pers = self.require_cookie("YNOTE_PERS").get("YNOTE_PERS", "")
        parts = ynote_pers.split("||")
        uid = parts[-2] if len(parts) >= 2 else "未获取到账号信息"

        http = self.http()
        # 第一步：换一个会话 cookie，后续请求都要带新的
        refreshed = http.get(self.url(REFRESH_API), params={"product": "YNOTE"})
        http.replace_cookies(dict(refreshed.cookies))

        # 第二步：同步。它同时也是登录态是否有效的判据 ——
        # 失效时接口回一段带 "error" 的 JSON（HTTP 可能是 500）
        result = Result()
        result.add("帐号信息", uid)
        sync = http.json("POST", self.url(SYNC_API), params={"method": "sync"})
        if "rewardSpace" not in sync:
            raise CheckInError("Cookie 可能过期，请重新登录后复制")

        # 第三步：签到本身
        checkin = http.json("POST", self.url(USER_API), params={"method": "checkin"})
        checkin_space = checkin.get("space", 0) // MB

        # 第四步：刷广告奖励。任一轮失败不影响主流程，跳过即可。
        ad_space = 0
        for _ in range(AD_ROUNDS):
            try:
                reward = http.json("POST", self.url(USER_API), params={"method": "adRandomPrompt"})
            except CheckInError:
                break
            ad_space += reward.get("space", 0) // MB

        total = sync.get("rewardSpace", 0) // MB + checkin_space + ad_space
        result.add("获取空间", f"+{total}M")
        return result