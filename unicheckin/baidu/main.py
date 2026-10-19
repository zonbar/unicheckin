"""百度搜索资源平台的 sitemap 提交。

流程：读一次 sitemap 文本，然后按配置的次数反复 POST 上去，累计成功/失败条数。

原实现有两个问题：
1. ``remain`` 初始写死 100000，而面板元数据里默认次数也是 100 —— 两者毫无关系，
   首条成功前显示的「剩余条数」是编出来的。改成 ``None``，用「—」占位。
2. 配置缺失时返回的是**字典**而不是列表，且下游按列表迭代会报错。
   现在缺配置直接抛 :class:`ConfigError`。
"""

import urllib.parse

from unicheckin import CheckIn, ConfigError, Result

SUBMIT_HOST = "https://data.zz.baidu.com"


class Baidu(CheckIn):
    name = "百度站点提交"
    base_url = SUBMIT_HOST

    def run(self) -> Result:
        data_url = self.option("data_url")
        submit_url = self.option("submit_url")
        if not data_url or not submit_url:
            raise ConfigError("请在设置里填写 sitemap 地址与提交接口地址")

        times = self.option_int("times", 100)
        site = self._site_of(submit_url)

        http = self.http()
        # sitemap 只需要读一次，后面每次提交都发同一份内容
        payload = http.get(str(data_url)).text

        remain = None  # 首次成功之前拿不到真实值，别编一个
        success_count = 0
        failure_count = 0

        for _ in range(max(1, times)):
            body = self._submit_once(http, str(submit_url), payload)
            if body.get("success"):
                remain = body.get("remain")
                success_count += body.get("success") or 0
            else:
                failure_count += 1

        result = Result()
        result.add("站点地址", site)
        result.add("剩余条数", remain)
        result.add("成功条数", success_count)
        result.add("成功次数", times - failure_count)
        result.add("失败次数", failure_count)
        return result

    # ------------------------------------------------------------------ #
    @staticmethod
    def _site_of(submit_url: str) -> str:
        """从提交接口地址里取出站点标识（查询参数里的 site）。"""
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(submit_url).query)
        site = qs.get("site") or []
        return site[0] if site else "—"

    def _submit_once(self, http, submit_url: str, payload: str) -> dict:
        """提交一次。单次失败不影响整体，只记为失败。"""
        try:
            resp = http.post(submit_url, data=payload.encode("utf-8"))
            body = resp.json()
        except Exception:  # noqa: BLE001 - 单次失败不该中断整轮
            return {}
        return body if isinstance(body, dict) else {}