"""全民 K 歌签到：领任务奖励 + 刷音乐卡片 + VIP 日签。

这个接口族的特点是 ``mapExt`` 里塞了一段 base64 编码的 protobuf 字段，
直接写在代码里是几十行肉眼无法校验的长串。这里把它们提���成模块级常量，
按名字引用 —— 出问题时能一眼看出是哪个字段，而不用在一堆百分号里找。

另外把「拿到音乐卡片列表」这段逻辑单独拆出来：原实现里它和签到流程
交叉在一起，一个 KeyError 会把整个签到带崩。
"""

import time
import urllib.parse

from unicheckin import CheckIn, CheckInError, Result

NODE = "https://node.kg.qq.com/webapp/proxy"

# ---- 请求模板 -------------------------------------------------------------- #
# 这些 base64 串是接口要求的 protobuf 字段，原样搬运（它们是协议而非创意表达）。
PROFILE_EXT = (
    "JTdCJTIyZmlsZSUyMiUzQSUyMnByb2ZpbGVfd2ViYXBwSmNlJTIyJTJDJTIyY21kTmFtZSUyMiUzQSUyMlByb2ZpbGVHZXQlMjIlMkMlMjJhcHBpZCUyMiUzQTEwMDA2MjYlMkMlMjJkY2FwaSUyMiUzQSU3QiUyMmludGVyZmFjZUlkJTIyJTNBMjA1MzU5NTk3JTdEJTJDJTIybDVhcGklMjIlM0ElN0IlMjJtb2RpZCUyMiUzQTI5NDAxNyUyQyUyMmNtZCUyMiUzQTI2MjE0NCU3RCUyQyUyMmlwJTIyJTNBJTIyMTAwLjExMy4xNjIuMTc4JTIyJTJDJTIycG9ydCUyMiUzQSUyMjEyNDA2JTIyJTdE"
)
LOTTERY_EXT = (
    "JTdCJTIyZmlsZSUyMiUzQSUyMnRhc2tKY2UlMjIlMkMlMjJjbWROYW1lJTIyJTNBJTIyTG90dGVyeVJlcSUyMiUyQyUyMnduc0NvbmZpZyUyMiUzQSU3QiUyMmFwcGlkJTIyJTNBMTAwMDU1NyU3RCUyQyUyMmw1YXBpJTIyJTNBJTdCJTIybW9kaWQlMjIlM0E1MDM5MzclMkMlMjJjbWQlMjIlM0E1ODk4MjQlN0QlN0Q%3D"
)
AWARD_EXT = (
    "JTdCJTIyZmlsZSUyMiUzQSUyMnRhc2tKY2UlMjIlMkMlMjJjbWROYW1lJTIyJTNBJTIyR2V0U2lnbkluQXdhcmRSZXElMjIlMkMlMjJ3bnNDb25maWclMjIlM0ElN0IlMjJhcHBpZCUyMiUzQTEwMDA2MjYlN0QlMkMlMjJsNWFwaSUyJTNBMQ=="
)
CARD_EXT = (
    "JTdCJTIyY21kTmFtZSUyMiUzQSUyMkdldEJhdGNoTXVzaWNDYXJkc1JlcSUyMiUyQyUyMmZpbGUlMjIlM0ElMjJwcm90b19tdXNpY19zdGF0aW9uSmNlJTIyJTJDJTIyd25zRGlzcGF0Y2hlciUyMiUzQXRydWUlN0Q"
)
# 领花奖励：交互类型 1 给 15 朵、类型 0 给 10 朵
REWARD_EXT = {
    15: "JTdCJTIyY21kTmFtZSUyMiUzQSUyMkdldFJld2FyZFJlcSUyMiUyQyUyMmZpbGUlMjIlM0ElMjJwcm90b19tdXNpY19zdGF0aW9uSmNlJTIyJTJDJTIyd25zRGlzcGF0Y2hlciUyMiUzQXRydWUlN0Q",
}
REWARD_QUERY = {
    15: "%7B%22uInteractiveType%22%3A1%2C%22uRewardType%22%3A0%2C%22uFlowerNum%22%3A15%7D",
    10: "%7B%22uInteractiveType%22%3A0%2C%22uRewardType%22%3A0%2C%22uFlowerNum%22%3A10%7D",
}

# 任务类型与入口的组合，逐个打过去即可
LOTTERY_TASKS = [("1", "1"), ("2", "1"), ("4", "104"), ("103", "4")]
AWARD_ENTRIES = ["1", "2", "4", "16", "128", "512"]

# 音乐卡片要试的开卡序号；命中 code 1000 表示今天已经开过
CARD_TRIES = 16

VIP_API = "https://node.kg.qq.com/webapp/proxy"
VIP_INFO = "ns=proto_vip_webapp&cmd=vip.get_vip_info"
VIP_REWARD = "ns=proto_vip_webapp&cmd=vip.get_vip_day_reward"


class KGQQ(CheckIn):
    name = "全民K歌"
    base_url = NODE
    min_interval = 0.4  # 站点对密集请求敏感，串行也要留间隔

    def run(self) -> Result:
        uid = self.require_cookie("uid").get("uid", "")
        http = self.http()

        before = self._profile(http, uid)
        self._collect_tasks(http, uid)
        card_msg = self._farm_music_cards(http, uid)
        vip_msg = self._vip_daily(http, uid)
        after = self._profile(http, uid)

        result = Result()
        result.add("帐号信息", before.get("nickname", "未知昵称"))
        result.add("获取鲜花", int(after.get("flower", 0)) - int(before.get("flower", 0)))
        result.add("当前鲜花", after.get("flower", 0))
        result.add("VIP 签到", vip_msg)
        if card_msg:
            result.add("开卡", card_msg)
        return result

    # ------------------------------------------------------------------ #
    def _call(self, http, query: str) -> dict:
        """打一次 node 代理接口，返回解析后的 JSON。

        失败返回空字典而不是抛异常 —— 这些任务接口本来就是
        「打到了就加分，没打到无所谓」，不该让整个签到失败。
        """
        url = f"{self.url('')}?{query}" if self.url("") else f"{NODE}?{query}"
        try:
            body = http.json("GET", url)
        except CheckInError:
            return {}
        return body if isinstance(body, dict) else {}

    @staticmethod
    def _dig(body: dict, path: str) -> dict:
        """按 ``ns.cmd`` 取内层对象，例如 ``profile.getProfile``。"""
        node = (body.get("data") or {}).get(path) or {}
        return node if isinstance(node, dict) else {}

    def _profile(self, http, uid: str) -> dict:
        body = self._call(http, f"ns=proto_profile&cmd=profile.getProfile&mapExt={PROFILE_EXT}&t_uUid={uid}")
        data = self._dig(body, "profile.getProfile")
        return {
            "nickname": (data.get("stPersonInfo") or {}).get("sKgNick", ""),
            "flower": data.get("uFlowerNum", 0),
        }

    def _collect_tasks(self, http, uid: str) -> None:
        """把各类任务奖励逐个领一遍。"""
        for entry in AWARD_ENTRIES:
            self._call(http, f"ns=KG_TASK&cmd=task.signinGetAward&mapExt={AWARD_EXT}&t_uid={uid}&t_iShowEntry={entry}")
        for entry, kind in LOTTERY_TASKS:
            self._call(http, f"ns=KG_TASK&cmd=task.getLottery&mapExt={LOTTERY_EXT}&t_uid={uid}&t_iShowEntry={entry}&t_type={kind}")

    def _farm_music_cards(self, http, uid: str) -> str:
        """刷音乐卡片领鲜花。返回一句说明（空串表示没刷到）。"""
        for seq in range(CARD_TRIES):
            body = self._call(
                http,
                f"ns=proto_music_station&cmd=message.batch_get_music_cards&mapExt={CARD_EXT}"
                f"&t_uUid={uid}&g_tk_openkey={seq}",
            )
            if body.get("code") == 1000:
                return "今日已开过卡"
            cards = self._dig(body, "message.batch_get_music_cards").get("vctMusicCards") or []
            if not cards:
                break
            best = max(cards, key=lambda c: (c.get("stReward") or {}).get("uFlowerNum", 0))
            flowers = (best.get("stReward") or {}).get("uFlowerNum", 0)
            if flowers <= 1:
                break  # 1 朵不值得开卡
            amount = 15 if flowers > 10 else 10
            self._call(
                http,
                f"t_stReward%3Aobject={REWARD_QUERY[amount]}&ns=proto_music_station"
                f"&cmd=message.get_reward&mapExt={REWARD_EXT[15]}"
                f"&t_uUid={uid}&t_strUgcId={best.get('strUgcId')}&t_strKey={best.get('strKey')}",
            )
            time.sleep(0.5)
        return ""

    def _vip_daily(self, http, uid: str) -> str:
        """VIP 日签。非 VIP 返回提示文案即可。"""
        info = self._call(http, f"{VIP_INFO}&t_uUid={uid}&t_uWebReq=1&t_uGetDataFromC4B=1")
        status = self._dig(info, "vip.get_vip_info").get("stVipCoreInfo") or {}
        if status.get("uStatus") != 1:
            return "非 VIP 用户"
        body = self._call(http, f"{VIP_REWARD}&ns_inbuf=&mapExt=JTdCJTIyY21kTmFtZSUyMiUzQSUyMkdldFZpcERheVJld2FyZCUyMiU3RA%3D%3D&g_tk_openkey=642424811")
        data = self._dig(body, "vip.get_vip_day_reward")
        return f"{data.get('strTips', '签到成功')} 获取VIP福利道具：{data.get('uCurRewardNum', 0)}个"