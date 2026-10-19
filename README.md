# Uni-Check-in

**签到聚合 + 网页管理后台。一条 `docker compose up -d` 跑起来，浏览器里点几下就配好了。**

[![build](https://github.com/zonbar/Uni-Check-in/actions/workflows/build.yml/badge.svg)](https://github.com/zonbar/Uni-Check-in/actions/workflows/build.yml)
[![ghcr](https://img.shields.io/badge/ghcr.io-uni--check--in-2496ed?logo=docker&logoColor=white)](https://github.com/zonbar/Uni-Check-in/pkgs/container/uni-check-in)
![license](https://img.shields.io/badge/license-MIT-green)

签到引擎最初改编自 [Sitoi/dailycheckin](https://github.com/Sitoi/dailycheckin)（MIT），
现已重构为独立实现，版权归 zonbar，按 MIT 发布。致谢见 [LICENSE](LICENSE)。

![后台效果图](index.png)

*卡片视图：一行 4 个站点，顶栏是签到概况统计。*

## 它解决什么

| 手工配置的做法 | 这里 |
|---|---|
| 手改 `config.json`，少个逗号就整个不跑 | 网页填表单，点保存，写错了直接告诉你错哪 |
| cookie 必须用 `; `（分号**加空格**）分隔 | 粘什么格式都认，自动规范化成引擎要的形态 |
| cookie 过期了没提醒，只能翻日志猜 | 卡片上直接标 ✅ 有效 / ❌ 失效 |
| 不知道某个站到底要哪几个字段 | 每个站点标出必填字段，缺了高亮 |
| 改定时时间要进容器改文件 | 网页选周期，保存即生效 |

## 快速开始

在任意目录新建 `docker-compose.yml`：

```yaml
services:
  unicheckin:
    image: ghcr.io/zonbar/uni-check-in:latest
    container_name: unicheckin
    restart: unless-stopped
    ports:
      - 8080:8080
    volumes:
      - ./config:/unicheckin/config
      - ./cron:/unicheckin/cron
      - ./logs:/unicheckin/logs
      - ./data:/unicheckin/data
    environment:
      - TZ=Asia/Shanghai
```

```bash
docker compose up -d
```

浏览器打开 `http://你的地址:8080`，第一次会引导你设置后台账号密码。

**升级**：两行一起复制粘贴，在**任意目录**跑都行 —— 第一行先从容器标签里问出 compose 文件在哪，第二行再跳过去更新：

```bash
D=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' unicheckin)
cd "$D" && docker compose pull && docker compose up -d
```

已经在 compose 目录里的话，只跑 `docker compose pull && docker compose up -d` 就够。设置页最下方的「关于本项目」显示当前构建的提交，并跟 GitHub 上 `main` 的最新提交比对 —— 有新提交就把上面这两行摊出来（点一下可整段选中复制）。

不用 compose 的话，拿同一个镜像挂上这**四个目录**用 `docker run` 起也行；Windows 把 `$PWD` 换成 `${PWD}`，群晖 / 威联通把上面这段贴进 Container Manager / Container Station 的「项目」。

想从源码构建（改了代码想本地验证、或镜像还没构建出来）：

```bash
docker compose -f docker-compose.build.yml up -d --build
```

### 数据放在哪

| 目录 | 内容 |
|---|---|
| `config/` | `config.json`，站点与 cookie |
| `cron/` | 定时任务定义 |
| `logs/` | 签到日志 |
| `data/` | 后台账号凭据、校验状态、运行历史、配置备份 |

删容器不丢数据，备份把这四个目录一起拷走。

## 网页后台

- **站点列表**：17 个站点铺成卡片（一行 4 张，右上角可切列表视图），带官网 LOGO、状态色条与徽章；顶部搜索按站名或 `KEY` 过滤（快捷键 `/`），可按分类筛选、「只看待配置」；排序默认「已配置优先」；窗口变窄自动降密度；跟随系统深浅色。登录过的人再打开**直接进管理界面**，不会先闪一屏登录页。
- **配置站点**：点卡片开配置窗，里面有「怎么拿 cookie」的说明和账号表单，底栏固定放「＋ 添加账号 / 立即签到 / 保存」。表单类站点（AcFun、阿里云盘这类）字段直接摊开，cookie 类站点的可选参数收在折叠条里。
- **cookie 随便粘**：浏览器复制的分号串、没空格的分号串、每行一个字段、DevTools 表格整块、JSON 导出、带 `Cookie:` 前缀的 curl 命令 —— 都认，自动规范化成 `; ` 分隔。
  > 引擎里多数站点写死 `cookie.split("; ")`，用 `;` 没空格或换行分隔会**静默解析错**、还不报错，所以面板替你补分隔符。
- **cookie 有效性**：三级递进 —— 格式体检（粘贴即出，指出缺哪个必填字段）→ 在线校验（请求站点登录态接口，返回昵称 / 等级 / 余额）→ 运行校验（跑真实签到）。结果存档在卡片徽章上并标注依据，**改动 cookie 后旧结论立刻作废**；遇到网络不通老实报「无法判定」，绝不误报失效。
  > 「跑通」不等于「有效」：不少模块遇到无效 cookie 是**静默返回**的（比如 B 站 `main()` 开头就 `if is_login:` 直接跳过），所以接口判定为 ❌ 的站点，跑签到没报错也继续标 ❌。
- **跑签到**：配置窗里单站跑，右上角「全部签到」跑全部；输出实时显示在右侧抽屉（可切当前任务 / 历史任务 / 日志）。
- **定时签到**：设置页选预设或自己填 cron，保存即写入容器 crontab。面板只动自己那段带标记的区块，你别的定时任务不受影响。
- **定时校验**：同样按 cron 定时（默认每 6 小时），只校验**已配置且有在线接口**的站点。全部有效时一声不响；有站点失效才推一条【Uni-Check-in 校验提醒】，同一批失效 24 小时内最多提醒一次。
- **推送通知**：支持（PushPlus、企业微信、Telegram、Bark、钉钉、飞书、Gotify、ntfy、Server 酱、Qmsg），只填要用的，每种渠道一个独立方框。**一次签到恒定一条消息**：

```text
【Uni-Check-in 每日签到】

「V2EX 论坛」
帐号信息: ABC
今日签到: 20261016 的每日登录奖励 13 铜币

————————————

「哔哩哔哩」
第 1 个账号: ✅✅✅✅✅

————————————

任务用时: 1 秒
项目地址: https://github.com/zonbar/Uni-Check-in
```

- **设置页**：后台账号密码 / `config.json` 原文编辑（语法错拒绝保存，每次保存前自动留时间戳备份，最多 30 份可一键恢复）/ 关于本项目。

## 支持的站点

清单从引擎里**自动发现** —— 加了新站，刷新面板就会出现，不用改代码。当前 17 个：

| 站点 | KEY | 凭据（必填） |
|---|---|---|
| 哔哩哔哩 | `BILIBILI` | Cookie `SESSDATA`、`bili_jct` |
| 百度贴吧 | `TIEBA` | Cookie `BDUSS` |
| 百度网盘 | `BAIDUWP` | Cookie `BDUSS` |
| 爱奇艺 | `IQIYI` | Cookie `P00001` |
| 有道云笔记 | `YOUDAO` | Cookie `YNOTE_PERS` |
| V2EX | `V2EX` | Cookie `A2` |
| 什么值得买 | `SMZDM` | 建议整块复制 |
| 奥拉星 | `AOLAXING` | Cookie `BT_LOGIN_tt_common` |
| 恩山无线论坛 | `ENSHAN` | Cookie `TWcq_2132_auth` |
| 飞牛 NAS 论坛 | `FNNASCLUB` | Cookie `pvRK_2132_auth` |
| 全民 K 歌 | `KGQQ` | Cookie `uid`、`openid`、`openkey` |
| 微博超话 | `WEIBO` | Cookie `SUB`（本项目新增，见下） |
| 阿里云盘 | `ALIYUN` | refresh_token |
| i 茅台 | `IMAOTAI` | `token`、`userid`、`mobile` 等 |
| AcFun | `ACFUN` | 账号密码 |
| 小米运动 | `MIMOTION` | 账号密码 |
| 百度站点提交 | `BAIDU` | 表单 |

新站**开箱可用**（能配、能存、能签到），只是精细度降一档：不拦必填字段、没有在线校验、LOGO 退回图标。想补全，照 `panel/catalog.py` 里已有写法加一段元数据即可。

### 微博超话（`WEIBO`，本项目新增）

签到**关注的超话**，默认只签「周杰伦」，可在站点设置里改成别的超话名（逗号分隔），或填 `all` 签全部。

取 cookie：登录 <https://m.weibo.cn/> → `F12` → Application → Cookies → `m.weibo.cn`，**必须复制 `SUB`**，建议整块复制（含 `SUBP` / `_T_WM`）。
`SUB` 的值几乎总是以 `==` 结尾，面板会完整保留 —— 这个站点用的是 `partition("=")` 解析，不会像其它站点那样被截断。

几点说明：

* 走的是 **m.weibo.cn 移动端接口**，不是 weibo.com 网页版。网页版 session 有 7 天硬性失效，移动端独立登录体系存活期更长。
* **必须先在微博里关注对应超话**，否则拉不到列表、签不了（面板会明确提示「没关注该超话」）。
* 微博对机房 IP 风控较严，返回 HTTP 432 时可在站点设置里填代理地址。
* 触发风控需要人工验证时，运行结果里会给出验证链接，点完再跑一次即可。

**怎么拿 cookie**：登录目标网站 → `F12` → **Application** → **Cookies** → 选中域名 → 表格里 `Ctrl+A` `Ctrl+C` 复制。或用 [Cookie-Editor](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm) 插件 **Export → JSON** 整块贴进来。
cookie 等于账号密码，**别外发** —— 它只存在你本机的 `config/config.json`，不会上传到任何地方。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `TZ` | `Asia/Shanghai` | 时区，影响定时任务时间 |
| `PANEL_PORT` | `8080` | 容器内监听端口（改这个要同步改 compose 映射） |
| `PANEL_TITLE` | `Uni-Check-in` | 浏览器标签 + 顶栏的品牌名 |
| `PANEL_USERNAME` / `PANEL_PASSWORD` | 空 | 想跳过「首次打开手动设账号」时填，只在后台还没初始化时生效 |
| `PANEL_TOKEN` | 空 | 可选的脚本口令，给 curl / 自动化用（`X-Panel-Token` 头或 `?token=`），**不能替代登录**，别开在公网 |
| `PANEL_RUN_TIMEOUT` | `1800` | 单次签到任务超时秒数 |
| `PANEL_REPO` | `zonbar/Uni-Check-in` | 「关于本项目」里的链接、以及「要不要更新」的比对对象 |
| `PANEL_GH_TOKEN` | 空 | 访问 GitHub 接口时带上它，避免匿名限流（60 次/小时/IP） |
| `DC_HOME` | `/unicheckin` | 工作目录，一般不用改 |

纯 Python 标准库实现，**零框架依赖**，x86 / arm64 / armv7 都能跑；后台密码只存 PBKDF2 派生值 + 随机盐，会话是签名票据（面板重启不掉线）；登录失败按 IP 限速。

## 引擎与开发

引擎源码**内置**在 `unicheckin/`，不从 PyPI 装：构建可复现、离线能编译。

新增一个签到站点只要两步，**不需要改任何注册表** —— 引擎用 `pkgutil.walk_packages`
自动扫描目录，面板也从引擎动态读取站点清单：

1. 建 `unicheckin/<key>/__init__.py`（空文件）与 `unicheckin/<key>/main.py`，
   写一个继承 `CheckIn` 的类，`name` 是中文站名，`main()` 返回签到结果文本；
2. 在 `panel/catalog.py` 补一段元数据（站名、图标、分类、必填 cookie 字段、
   可选配置项）—— 不补也能用，只是没有必填提示和在线校验按钮。

离线自测（全部不需要网络，跑一遍就知道有没有改坏）：

```bash
python3 tools/test_weibo.py            # 微博超话：卡片解析、cookie 不截断、超话名精确匹配、签到返回码
python3 tools/test_panel_static.py     # 前端契约：首屏不预置登录屏、卡片等高、localStorage 容错
python3 tools/test_notice.py           # 通知恒定一条
python3 tools/test_schedule.py         # crontab 托管区块不被覆盖
python3 tools/test_autoverify.py       # 定时校验：cron 算法、只在失效时通知、24 小时不重复
```

镜像由 GitHub Actions 构建：推 `main` 会跑冒烟测试再发布到
`ghcr.io/zonbar/uni-check-in`；提 PR 只跑测试不发布。

## 常见问题

**想挂到公网？**
① 登录后台设好账号密码（默认就要求登录，别关）；② 前面套一层 HTTPS 反向代理（Nginx / Caddy / Traefik）—— 会话票据是 Bearer 语义，明文 HTTP 有被截获的风险。反代记得转发 `X-Forwarded-Proto`，面板会据此给 cookie 加 `Secure`。

**从官方镜像 `sitoi/unicheckin` 迁过来要做什么？**
先停掉旧容器 —— 本项目容器名也叫 `unicheckin`，不清理会撞名：`docker stop unicheckin && docker rm unicheckin`。然后把原 `config/config.json` 复制到本项目 `config/`，`docker compose up -d` 即可。

**校验显示「无法判定」是不是 cookie 坏了？**
不一定。网络不通、接口改版、被风控都会这样，面板宁可不确定也不误报失效。这种情况点「立即签到」：**报错了一定有问题，没报错也不能证明有效**。

**在 root 目录直接跑 `docker compose pull` 报 `no configuration file provided`？**
compose 只认**当前目录**里的 `docker-compose.yml`。用上面「升级」那两行（会自己定位目录），或者先 `cd` 到放 compose 的目录。不知道自己项目在哪，跑 `docker compose ls` —— 它会把每个项目用的配置文件路径列出来。

## 本地开发

```bash
pip install -r requirements.txt    # 只有引擎需要（requests / pycryptodome / rsa / urllib3）
python -m panel                    # 默认监听 0.0.0.0:8080
```

即使引擎导入失败（比如 `requests` 没装好），面板也能起来并给出提示，不会白屏。从源码构建镜像用 `docker compose -f docker-compose.build.yml up -d --build`。

目录：`panel/` 后台（纯标准库）、`unicheckin/` 引擎、`tools/` 离线自测、`docker/entrypoint.sh` 容器入口。

## 致谢与许可

签到引擎最初改编自 [Sitoi/dailycheckin](https://github.com/Sitoi/dailycheckin)（作者 Sitoi），
现已重构为独立实现。此项目原作的作者与许可声明在此致谢；
仓库中现存的代码版权归 zonbar，按 MIT 发布。详见 [LICENSE](LICENSE)。
