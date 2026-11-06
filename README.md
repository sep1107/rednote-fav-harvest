# Rednote Fav Harvest 小红书收藏采集

把自己账号的小红书**收藏笔记列表**导出成结构化数据：`note_id`、类型（视频/图文）、标题、`xsec_token`、封面。

在一台无头 Linux 服务器上跑，登录只需要用手机扫一次码。输出可以直接拼成可抓取的笔记 URL，交给下游的剪藏／转录流程。

```
{"note_id":"...","type":"video","title":"...","xsec_token":"...","token_at":1786190449,"cover":"https://..."}
```

## 它是怎么拿到数据的

**不爬 DOM，不伪造签名，而是读浏览器自己发出的请求的响应。**

收藏列表接口是 `https://edith.xiaohongshu.com/api/sns/web/v2/note/collect/page`，它要求 `x-s` / `x-t` 签名头，由站点前端 JS 生成。裸 `fetch` 打这个接口会被拒：

```
HTTP 406  {"code":-1,"success":false}
```

所以本工具不去复现签名算法（那玩意儿一改就废），而是：

1. 在服务器上跑一个登录态的无头 Chromium，开着 CDP 调试端口；
2. 按 URL 主机名选择小红书标签页（不会使用其他网站的标签页），通过 CDP 订阅 `Network.responseReceived` / `Network.loadingFinished`；
3. 激活小红书标签页，读取页面内嵌的首屏收藏，再滚动实际可滚动容器，读取后续分页响应；
4. 按 `note_id` 去重入库。

签名、鉴权、分页游标全部由站点前端负责，工具只负责滚动和记账。小红书改签名算法不影响本工具。

**爬 DOM 是行不通的**：收藏列表是虚拟滚动，任何时刻 DOM 里只有十几张卡片，而且卡片上只有 `data-note-id`，没有 `xsec_token`。

## 只读

全程只有导航和滚动。不点赞、不评论、不关注、不取消收藏，不触碰任何会改变账号状态的控件。

## 依赖

- Linux（本项目在 Ubuntu 24.04 / aarch64 上开发和验证）
- Chromium（snap 版即可）
- Python 3.11+ 与 `python3-websockets`
- CJK 字体（否则界面全是方块，扫码时找不到按钮）

```bash
sudo snap install chromium
sudo apt-get install -y python3-websockets fonts-noto-cjk
```

## 起浏览器

```bash
cp browser/xhs-browser.sh ~/xhs-browser.sh && chmod +x ~/xhs-browser.sh
mkdir -p ~/.config/systemd/user && cp browser/xhs-browser.service ~/.config/systemd/user/
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload && systemctl --user enable --now xhs-browser
```

**必须用 systemd user service，不能 `nohup` 挂在 SSH 上**，原因见下面的「踩过的坑」。

## 登录（扫码，不碰密码）

调试端口只绑 `127.0.0.1`。从你自己的机器建隧道：

```bash
ssh -N -L 9222:127.0.0.1:9222 <your-server>
```

然后在本地浏览器打开：

```bash
open "http://localhost:9222/devtools/inspector.html?ws=localhost:9222/devtools/page/$(curl -s http://localhost:9222/json/list | python3 -c 'import sys,json;from urllib.parse import urlsplit;print([t["id"] for t in json.load(sys.stdin) if t["type"]=="page" and urlsplit(t.get("url","")).hostname in ("xiaohongshu.com","www.xiaohongshu.com")][0])')"
```

DevTools 要 10–15 秒才附着，标题变成 `DevTools - www.xiaohongshu.com/...` 才算连上，在那之前是白屏，正常。主面板就是服务器上那个浏览器的实时画面，点「登录」，二维码显示在**你自己的屏幕上**，手机扫码并在手机上确认。

登录态落在浏览器 profile 里，重启浏览器不丢。撤销就删掉 profile 目录。

## 采集

```bash
python3 harvest.py                  # 全量，按 note_id 去重，可反复跑
python3 harvest.py --max-minutes 30
```

产物（与脚本同目录）：

| 文件 | 内容 |
|---|---|
| `favorites.jsonl` | 每条收藏一行，`note_id` 为主键 |
| `state.json` | 总数、本次新增、接口页数、停止时的 `has_more`、类型分布 |
| `pages.log` | 逐页累积日志，便于事后核对 |

实测约 **1.8 秒一页 / 每页 10 条**，4300 条约 20 分钟。

### note_id 是持久键，xsec_token 会过期

`note_id` 永不变，`xsec_token` 有有效期，所以每行都带 `token_at` 时间戳。如果你打算「先攒链接、之后慢慢处理」，处理前重跑一次采集刷新 token 即可——全量重跑只要 20 分钟，比设计断点续传划算得多。

拼 URL 的形态：

```
https://www.xiaohongshu.com/explore/<note_id>?xsec_token=<token>&xsec_source=pc_feed
```

## 增量采集

全量跑完之后，日常只需要从列表顶部扫到遇见已知条目为止：

```bash
python3 harvest.py --incremental --stop-after 3
python3 rebuild_queue.py      # 重建待处理队列
```

实测约 10 秒、扫 4 页即停。

**增量与全量的停机判据相反，这一点值得注意。** 全量续跑时开头必然是上百页已知条目，
若据此停机就永远够不到新数据 —— 全量只认接口返回的 `has_more=False`。
而增量从列表顶部开始，撞到已知内容正是该停的信号。所以是显式的 `--incremental` 开关，
不共用一套逻辑。

`rebuild_queue.py` 由「采集库 − 已处理 − 跳过名单」推导出待处理队列，按收藏时间倒序，
新条目天然排在队首。队列是派生产物，不手工维护 —— 两份手工维护的「还剩什么没做」一定会漂移。

它读取脚本同目录下的：

| 文件 | 作用 |
|---|---|
| `favorites.jsonl` | 采集库（本工具产出）|
| `out/clipped.jsonl` 或 `clipped_ids.txt` | 已处理的 `note_id` |
| `skip.jsonl` | 人工判定不再处理的 `note_id` |

后两者的格式由下游流程决定，本工具只读 `note_id` 字段；文件不存在时按空集处理。

## 一个必须说清的边界：枚举拿不全

页面上显示「笔记・6773」，接口枚举到 4294 条就 `has_more=False` 了，差约 2479 条。

已经查过的：

- **不是有损分页。** 两次完全独立的全量扫描，结果 4293 / 4294 条，交集 4293，一方独有 0 / 1 条。重复跑不会收敛出更多。
- **不是时间截断。** 结果覆盖 2019-11 到 2026-07，每年都有。
- **不全是「笔记被删了」。** 拿 9 条「确定收藏过、但不在枚举结果里」的笔记去实测，**6 条页面完整、标题和媒体都对得上，是活的**；3 条返回 302 空壳（作者删除或转私密）。同批对照组 9/9 全活，排除了 token 过期的干扰。

所以差额里**既有作者删除／隐藏的，也有活着却未被枚举的**。

**比例无法测定**：能拿来做实验的只有那些「碰巧从别处知道 id」的笔记，剩下两千多条枚举不出来就拿不到 id，没有取样办法。别把上面 9 条的比例外推到全体。

如果你需要完整的收藏，这个工具**不能**满足你。

## 踩过的坑

按代价从大到小：

1. **UA 里的 `HeadlessChrome` 会让页面自己把 `<body>` 删掉。** 表现是彻底白屏、30 个报错、DOM 里只剩 `<html><head>`，而不是任何形式的验证码或封禁提示。加上正常的 `--user-agent` 和 `--lang=zh-CN` 就恢复了。

2. **`Page.navigate` 会让 CDP 的响应体失效。** 导航过程中发出的第一页请求，等你去 `Network.getResponseBody` 时正文已被回收。如果代码对空正文静默 `continue`，就会**丢一整页却毫无报错**。本工具把空正文单独计数并打印出来。

3. **snap 版 Chromium 不能用 `nohup` / `dbus-run-session` 挂在 SSH 会话上。** SSH 一断，会话 D-Bus 销毁，Chromium 直接 `FATAL: D-Bus connection was disconnected. Aborting.`；改用 `dbus-run-session` 会撞上 snap 的 cgroup 检查（`session-xxx.scope is not a snap cgroup for tag snap.chromium.chromium`）。**systemd user service + `loginctl enable-linger` 一次解决两个问题。**

4. **snap 封装下 `$HOME` 里的隐藏目录不可写**，`--user-data-dir` 不能用 `~/.xxx`，要用 `~/snap/chromium/common/...` 这类非隐藏路径。

5. **「连续 N 页无新条目 = 到底」是错的判据。** 续跑时开头必然重复上百页，会被误判成到底。**唯一可靠的到底信号是接口自己返回的 `has_more=False`。**

6. **滚动策略实测有差异**（每次动作触发的接口页数）：跳到底部 1.0、渐进 `scrollBy` 1.0、**先上抬 300px 再下探 900px 约 1.8** —— 本工具用第三种。

7. **别靠文本匹配去点 tab。** 「笔记」既是主 tab 也是子 tab（`笔记・6773`），松散匹配会点飞到别的页面。要么用带「・」的判据区分，要么干脆别点。

8. **采集期屏蔽图片请求**（封面 URL 接口里已经有了，不必真下载）——虚拟滚动几千页时内存和带宽都省下来。

## 回归检查

```bash
python3 -m unittest -v test_harvest
node test_browser.js
```

分别覆盖标签页域名选择，以及内嵌首屏数据和两种滚动布局；Node.js 仅用于开发测试，采集运行不需要。

## 授权与用途

只用于导出**你自己账号**的收藏数据，属于个人数据导出。请遵守小红书的服务条款，不要用于批量抓取他人内容或商业用途。

## License

MIT
