"""签到站点模块的公共基类。

为什么要有这层
----------------
17 个站点里有 15 个做的事其实是同一套流程，只是接口地址和解析方式不同：

    读配置 -> 建 Session（塞 cookie / 代理 / UA）-> 发几个请求 -> 拼结果文本

原先这套流程在每个模块里各抄一遍，抄出了几个反复出问题的地方：

- cookie 解析写成 ``{i.split("=")[0]: i.split("=")[1] for i in cookie.split("; ")}``。
  这行有两个坑：值里含 ``=`` 会被截断（微博的 SUB 几乎总是以 ``==`` 结尾，
  一截断就是失效的 cookie）；浏览器里用 ``;`` 无空格或换行分隔会整条解析错。
- 站点接口挂了就直接抛 requests 的原始异常，用户看到的是
  ``Max retries exceeded with url: ...`` 这种没法排查的东西。
- 超时、重试、限速各写一遍，有的写了有的没写。

现在统一收敛到 ``CheckIn`` 与 ``HttpSession``：站点模块只描述「打哪个接口、
怎么从响应里取数据」，其余交给基类。

对外约定（改动会影响面板与既有配置，务必保持）
--------------------------------------------------
* 站点 KEY = 类名大写（``configs.checkin_map`` 靠这个索引）
* ``name`` = 卡片上显示的中文名
* 构造签名 ``Cls(check_item=<dict>)``
* ``main()`` 返回 str，每行 ``"标题: 值"``
* 配置不完整时抛异常 —— 面板靠异常把卡片标红
"""

from __future__ import annotations

import pkgutil
import time
from typing import Any, Optional

__all__ = [
    "CheckIn",
    "HttpSession",
    "CheckInError",
    "ConfigError",
    "Result",
    "parse_cookie",
    "DEFAULT_UA",
    "MOBILE_UA",
]

# 桌面 Chrome 的 UA。多数站点走移动端 H5 接口，用 MOBILE_UA 覆盖。
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)


class CheckInError(Exception):
    """签到过程中的可读错误。

    引擎会把它当普通异常往外抛，面板捕获后显示 ``message``。
    继承 ``RuntimeError`` 而非直接继承 ``Exception``，
    便于调用方区分「预期的失败」与「代码有 bug」。
    """


class ConfigError(CheckInError, ValueError):
    """配置缺失或不合法。

    同时继承 ``ValueError``：历史上部分站点在构造期抛的是 ``ValueError``，
    保持这个 isinstance 关系，向后兼容既有调用方。
    """


def parse_cookie(raw: Any) -> dict:
    """把 Cookie 串解析成 ``{name: value}``。

    和引擎原来那句 ``split("=")[1]`` 的区别有两处，都是为了不再静默出错：

    - 用 ``partition`` 只切第一个 ``=``，值里含 ``=`` 不会被截断
      （Base64 类字段普遍以 ``==`` 结尾）
    - ``;`` 后有无空格、换行分隔都认

    无法解析的片段会被跳过而不是让整条 cookie 报废 ——
    少一个无关字段不该让签到直接失败。
    """
    if not raw:
        return {}
    if isinstance(raw, dict):  # 面板存盘时可能已是字典
        return {str(k): str(v) for k, v in raw.items()}

    text = str(raw).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", ";")  # 每行一个字段是常见的另一种粘贴形态

    out: dict = {}
    for part in text.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        if name:
            out[name] = value.strip()
    return out


class Result:
    """一次签到的结果，累积若干「标题: 值」条目。

    用它替代到处 return 的 ``[{"name": ..., "value": ...}, ...]`` 字典列表：
    原来每个站点都要写一遍 ``"\\n".join(f"{x['name']}: {x['value']}")``，
    现在由 :meth:`render` 统一负责。
    """

    __slots__ = ("items",)

    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []

    def add(self, title: str, value: Any) -> "Result":
        """追加一条。``value`` 为 None / 空串时写入占位符，避免出现「标题: 」残行。"""
        self.items.append((str(title), "—" if value in (None, "") else str(value)))
        return self

    def extend(self, pairs) -> "Result":
        for title, value in pairs:
            self.add(title, value)
        return self

    def flag(self, title: str, ok: bool, detail: str = "") -> "Result":
        """追加一条带 ✅/❌ 前缀的记录，用于成败混合的场景。"""
        return self.add(title, f"{'✅' if ok else '❌'} {detail}".strip())

    def render(self) -> str:
        """转成面板与通知直接渲染的文本。"""
        return "\n".join(f"{title}: {value}" for title, value in self.items)

    def __bool__(self) -> bool:
        return bool(self.items)

    def __len__(self) -> int:
        return len(self.items)


class HttpSession:
    """站点模块共用的 HTTP 会话。

    统一处理 cookie、代理、UA、超时、重试、限速与错误翻译，
    让站点模块只关心业务逻辑。
    """

    def __init__(
        self,
        cookie: Optional[dict] = None,
        *,
        proxy: str = "",
        user_agent: str = DEFAULT_UA,
        timeout: int = 15,
        retries: int = 3,
        verify: bool = True,
        headers: Optional[dict] = None,
        min_interval: float = 0.0,
    ) -> None:
        import requests  # 延迟导入：面板零依赖也能 import 这个模块

        self._requests = requests
        self.timeout = timeout
        self.retries = max(1, retries)
        self.min_interval = min_interval
        self._last_request_at = 0.0

        self.session = requests.Session()
        if not verify:
            # 少数站点的证书链在容器里验不过；urllib3 的告警太吵，一并关掉。
            requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
            self.session.verify = False

        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )
        if headers:
            self.session.headers.update(headers)
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        if cookie:
            requests.utils.add_dict_to_cookiejar(self.session.cookies, cookie)

    def _throttle(self) -> None:
        """按 ``min_interval`` 控制请求间隔，别把人家站点打挂。"""
        if self.min_interval <= 0:
            return
        if self._last_request_at:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
        self._last_request_at = time.monotonic()

    def _once(self, method: str, url: str, **kwargs):
        self._throttle()
        kwargs.setdefault("timeout", self.timeout)
        return self.session.request(method, url, **kwargs)

    def request(self, method: str, url: str, **kwargs):
        """带重试的请求。

        5xx 与网络异常会重试（指数退避）；4xx 不重试 —— 那通常是
        「cookie 无效」这类重试也没用的情形，交给调用方判断。
        """
        last: Optional[CheckInError] = None
        for attempt in range(self.retries):
            try:
                resp = self._once(method, url, **kwargs)
                if resp.status_code < 500:
                    return resp
                last = CheckInError(f"HTTP {resp.status_code}")
            except self._requests.RequestException as exc:
                last = CheckInError(f"网络请求失败：{exc}")
            if attempt < self.retries - 1:
                time.sleep(0.5 * (2**attempt))
        raise last or CheckInError("请求失败")

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def replace_cookies(self, jar) -> "HttpSession":
        """用新的 cookie 字典替换整个会话的 cookie。

        有些站点在登录态校验通过后会下发新的会话 cookie，后续请求必须换成它。
        提供这个方法是为了让站点模块不用去摸 ``session.cookies``——
        直接操作 requests 的 cookiejar 既难读也不好测。
        """
        self.session.cookies.clear()
        for name, value in (jar or {}).items():
            self.session.cookies.set(str(name), str(value))
        return self

    def adopt_cookies(self, resp) -> "HttpSession":
        """把某个响应带来的新 cookie 并进当前会话（不清空原有的）。"""
        for name, value in getattr(resp, "cookies", {}) or {}.items():
            self.session.cookies.set(str(name), str(value))
        return self

    def json(self, method: str, url: str, **kwargs) -> dict:
        """请求并解析 JSON。解析失败抛可读异常。"""
        resp = self.request(method, url, **kwargs)
        try:
            data = resp.json()
        except ValueError as exc:
            raise CheckInError(f"接口返回的不是 JSON（HTTP {resp.status_code}）") from exc
        if not isinstance(data, dict):
            raise CheckInError("接口返回的 JSON 结构不是对象")
        return data

    def text(self, method: str, url: str, **kwargs) -> str:
        return self.request(method, url, **kwargs).text


class CheckIn:
    """所有签到站点的基类。

    子类最少只需要::

        class Demo(CheckIn):
            name = "示例"
            base_url = "https://demo.example.com"

            def run(self) -> Result:
                data = self.http().json("GET", self.url("/api/checkin"))
                r = Result()
                r.add("帐号信息", data.get("user"))
                r.add("今日签到", "成功")
                return r

    ``run()`` 返回 :class:`Result`（或直接返回 str），``main()`` 负责渲染。
    需要完全自定义输出时覆写 ``main()``。
    """

    #: 卡片上显示的中文名
    name = "基类"

    #: 站点根地址，配合 ``url()`` 用，避免每处硬编码域名
    base_url = ""

    #: 该站点用的 UA
    user_agent = DEFAULT_UA

    #: 请求超时（秒）
    timeout = 15

    #: 失败重试次数
    retries = 3

    #: 相邻两次请求的最小间隔（秒），0 表示不限速
    min_interval = 0.0

    def __init__(self, check_item: dict):
        self.check_item = check_item or {}
        self._session: Optional[HttpSession] = None

    # ------------------------------------------------------------------ #
    # 配置读取
    # ------------------------------------------------------------------ #
    @property
    def cookie(self) -> dict:
        """当前账号的 cookie（已解析成字典）。"""
        return parse_cookie(self.check_item.get("cookie"))

    def cookie_value(self, key: str, default: str = "") -> str:
        """取单个 cookie 字段。"""
        return self.cookie.get(key, default)

    def require_cookie(self, *keys: str) -> dict:
        """要求若干 cookie 字段必须存在，否则抛 :class:`ConfigError`。

        在请求前调用，能把「cookie 复制不全」这类问题在最早的时机暴露出来，
        而不是等站点接口返回一段看不懂的错误。
        """
        jar = self.cookie
        if not jar:
            raise ConfigError("必须提供 Cookie")
        missing = [key for key in keys if not jar.get(key)]
        if missing:
            raise ConfigError(f"Cookie 中缺少 {'、'.join(missing)}，请重新登录后完整复制")
        return jar

    def option(self, key: str, default: Any = None) -> Any:
        """读站点自己的可选项（面板里那些可折叠配置）。"""
        value = self.check_item.get(key, default)
        return default if value in (None, "") else value

    def option_int(self, key: str, default: int) -> int:
        try:
            return int(self.option(key, default))
        except (TypeError, ValueError):
            return default

    def option_bool(self, key: str, default: bool = False) -> bool:
        raw = self.check_item.get(key, default)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        return str(raw).strip().lower() in ("1", "true", "yes", "on")

    @property
    def proxy(self) -> str:
        return str(self.check_item.get("proxy") or "").strip()

    # ------------------------------------------------------------------ #
    # HTTP
    # ------------------------------------------------------------------ #
    def http(self, **overrides) -> HttpSession:
        """拿到本账号的会话对象。

        同一个实例会被复用 —— 每次新建 session 意味着每次都要重新握手 TCP 与 TLS，
        这是原来 17 个站点各建一个 session 时最明显的开销来源。
        """
        if self._session is None:
            params: dict = {
                "cookie": self.cookie,
                "proxy": self.proxy,
                "user_agent": self.user_agent,
                "timeout": self.timeout,
                "retries": self.retries,
                "min_interval": self.min_interval,
            }
            params.update(overrides)
            self._session = HttpSession(**params)
        return self._session

    def url(self, path: str) -> str:
        """拼绝对地址。站点实现里用它代替到处硬编码域名。"""
        if path.startswith(("http://", "https://")):
            return path
        if not self.base_url:
            return path
        return self.base_url.rstrip("/") + "/" + path.lstrip("/")

    # ------------------------------------------------------------------ #
    # 执行
    # ------------------------------------------------------------------ #
    def run(self):
        """站点逻辑，返回 :class:`Result` 或 str。子类通常只实现这个。"""
        raise NotImplementedError("子类必须实现 run()")

    def main(self) -> str:
        """引擎与面板的调用入口，返回可直接渲染的文本。"""
        outcome = self.run()
        if isinstance(outcome, Result):
            return outcome.render()
        return str(outcome)


# --------------------------------------------------------------------------- #
# 站点自动发现
#
# 靠遍历本目录下的子包完成，每个站点模块 import 时会把自己的类注册到
# CheckIn 的子类里，configs.checkin_map 再从 __subclasses__() 收集。
# 排除 main / configs / utils —— 前两个是入口与配置，utils 不是站点。
# --------------------------------------------------------------------------- #
__path__ = pkgutil.extend_path(__path__, __name__)
_NON_SITE = {"unicheckin.main", "unicheckin.configs"}
for _finder, _modname, _ in pkgutil.walk_packages(__path__, prefix=__name__ + "."):
    if _modname not in _NON_SITE:
        __import__(_modname)