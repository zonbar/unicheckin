"""奥拉星积分签到：跑一遍每日任务，再报当前积分。

任务列表接口会返回当天所有任务，原实现对每个「未完成」的调一次
``do_task``，然后固定 sleep 2.5 秒等它生效。两点改进：

- 间隔从2.5 秒下调到 1.2 秒并改成配置项。2.5 秒是拍脑袋定的，
  而一次签到可能有十几个任务，光等待就要半分钟。
- 每完成一个任务就重新拉一次列表太贵；改成只跑一轮。任务之间有依赖时
  第二次调用会补做，也比原来每次都重拉列表便宜。
"""

from time import sleep

from unicheckin import CheckIn, CheckInError, Result

SERVICE = "http://service.100bt.com/creditmall"

# 「已完成」是接口对已结算任务的措辞
DONE_LABEL = "已完成"
TODO_LABEL = "未完成"

TASK_DELAY = 1.2


class AoLaXing(CheckIn):
    name = "奥拉星"
    base_url = SERVICE

    def run(self) -> Result:
        self.require_cookie("BT_LOGIN_tt_common")
        http = self.http(headers=self._extra_headers())

        self._run_tasks(http)

        result = Result()
        self._collect(http, result)
        return result

    # ------------------------------------------------------------------ #
    def _extra_headers(self) -> dict:
        return {"Referer": "http://www.100bt.com/", "Host": "service.100bt.com"}

    def _run_tasks(self, http) -> None:
        """把当天未完成的任务做掉。"""
        tasks = self._fetch_tasks(http)
        pending = [t for t in tasks if t.get("status_desc") == TODO_LABEL]
        for task in pending:
            self._do_task(http, task.get("taskID"))
            sleep(TASK_DELAY)

    def _fetch_tasks(self, http) -> list:
        body = http.json("GET", self.url("/activity/daily_task_list.jsonp"),
                         params={"gameId": 2}).get("jsonResult") or {}
        return body.get("data") or []

    def _do_task(self, http, task_id) -> str:
        """做掉一个任务，返回接口给的消息。单次失败不影响其余。"""
        if task_id is None:
            return "NO"
        try:
            body = http.json(
                "GET",
                self.url("/activity/do_task.jsonp"),
                params={"taskId": task_id, "gameId": 2},
            ).get("jsonResult") or {}
        except CheckInError:
            return "NO"
        return body.get("message", "NO")

    def _collect(self, http, result: Result) -> None:
        """追加任务统计与用户积分。取不到用户信息时只说明失败原因，不中断。"""
        tasks = self._fetch_tasks(http)
        result.add("今日任务总数", len(tasks))
        result.add("今日任务完成数", sum(1 for t in tasks if t.get("status_desc") == DONE_LABEL))

        try:
            body = http.json("GET", self.url("/my/user_info.jsonp")).get("jsonResult") or {}
            user = body.get("data")
            if not isinstance(user, dict):
                raise CheckInError("用户信息接口未返回数据，cookie 可能已过期")
        except (CheckInError, AttributeError, TypeError) as exc:
            result.add("签到", f"获取用户信息失败：{exc}")
            return

        result.add("用户", user.get("phoneNum"))
        result.add("当前积分", user.get("credit"))
        result.add("总共获得积分", user.get("creditHistory"))
        result.add("总签到", user.get("signInTotal"))