"""阿里云盘签到。

两段式：先用 refresh_token 换一个短期 access_token，再用它查签到记录并领奖励。

``sign()`` 原来的实现有个 bug：token 失效时 ``main()`` 直接
``return [{"name": ..., "value": "token 过期"}]`` —— 返回的是列表而不是字符串，
调用方（面板 / 通知）会把它当文本渲染，结果输出变成一串 Python 字面量。
现在统一抛 :class:`CheckInError`，由基类渲染成正常文本。
"""

from unicheckin import CheckIn, CheckInError, Result

TOKEN_API = "https://auth.aliyundrive.com/v2/account/token"
SIGN_LIST_API = "https://member.aliyundrive.com/v1/activity/sign_in_list"
SIGN_REWARD_API = "https://member.aliyundrive.com/v1/activity/sign_in_reward"


class AliYun(CheckIn):
    name = "阿里云盘"
    base_url = "https://member.aliyundrive.com"

    def run(self) -> Result:
        refresh_token = self.check_item.get("refresh_token")
        if not refresh_token:
            raise CheckInError("请在设置里填写 refresh_token")

        access_token = self._exchange_token(str(refresh_token))
        detail = self._sign_in(access_token)

        result = Result()
        if detail["has_reward"]:
            result.add("累计签到", detail["count"])
            result.add("阿里云盘", f"获得奖励：{detail['reward']}")
        else:
            result.add("阿里云盘", "签到成功，今日未获得奖励")
        return result

    # ------------------------------------------------------------------ #
    def _exchange_token(self, refresh_token: str) -> str:
        """用 refresh_token 换 access_token。

        这个接口不用带鉴权头，所以单独走一次裸请求，
        不复用带 Cookie 的会话。
        """
        http = self.http()
        payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        resp = http.post(TOKEN_API, json=payload)
        try:
            data = resp.json()
        except ValueError as exc:
            raise CheckInError("token 接口返回的不是 JSON") from exc

        token = data.get("access_token")
        if not token:
            # 失效时接口回 {"code": "...", "message": "..."}
            raise CheckInError(f"refresh_token 已失效：{data.get('message') or data.get('code') or '未知原因'}")
        return str(token)

    def _sign_in(self, access_token: str) -> dict:
        """查签到记录并领当天的奖励，返回奖励描述与累计天数。"""
        headers = {"Authorization": access_token, "Content-Type": "application/json"}
        payload = self.http().post(SIGN_LIST_API, headers=headers, json={})
        body = payload.json() if hasattr(payload, "json") else {}
        inner = body.get("result") or {}
        if not inner:
            raise CheckInError(f"签到接口未返回结果：{body.get('message') or '可能是 access_token 已过期'}")

        count = inner.get("signInCount", 0)
        # 领奖要带上累计天数
        self.http().post(
            SIGN_REWARD_API, headers=headers, data={"signInDay": count}
        )

        return {
            "count": count,
            "has_reward": self._today_reward(inner),
            "reward": self._reward_text(inner),
        }

    # ------------------------------------------------------------------ #
    @staticmethod
    def _today_logs(inner: dict) -> list:
        return inner.get("signInLogs") or []

    @classmethod
    def _today_entry(cls, inner: dict) -> dict:
        """取「今天」那条签到记录。

        ``signInLogs`` 按日期倒序，最新的一条 ``status`` 是 ``miss``（待签到），
        它**前面**那条才是今天已签到的记录 —— 所以取 ``miss`` 下标的上一条。

        ``miss`` 出现在下标 0 时说明列表里只有这条待签记录、没有今天的历史，
        此时返回空字典，由调用方按「未获得奖励」处理。
        """
        logs = cls._today_logs(inner)
        for i, one in enumerate(logs):
            if one.get("status") == "miss" and i > 0:
                return logs[i - 1]
        return {}

    @classmethod
    def _today_reward(cls, inner: dict) -> bool:
        return bool(cls._today_entry(inner).get("isReward"))

    @classmethod
    def _reward_text(cls, inner: dict) -> str:
        reward = cls._today_entry(inner).get("reward") or {}
        return f"{reward.get('name', '')}{reward.get('description', '')}"