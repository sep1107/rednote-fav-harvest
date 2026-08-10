#!/usr/bin/env python3
"""Harvest the full Rednote favorites list off the wire via CDP.

Durable key: note_id. xsec_token is perishable and refreshed by later runs.
Read-only against Rednote: navigates and scrolls only; never clicks a favorite control.
Store: favorites.jsonl (one row per note_id, newest token wins) + state.json.
"""
import argparse, asyncio, json, os, sys, time, urllib.request
import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "favorites.jsonl")
STATE = os.path.join(HERE, "state.json")
CDP = "http://127.0.0.1:9222"
BLOCKED = ["*sns-webpic*", "*sns-avatar*", "*sns-img*", "*.jpg", "*.jpeg", "*.png", "*.webp", "*.gif"]
# 实测最有效：先上抬再下探，比单纯跳到底部触发率高
SCROLL = "(function(){window.scrollBy(0,-300);setTimeout(function(){window.scrollBy(0,900)},200)})()"


def load_store():
    rows = {}
    if os.path.exists(STORE):
        for line in open(STORE, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    r = json.loads(line)
                    rows[r["note_id"]] = r
                except Exception:
                    pass
    return rows


def save_store(rows):
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, STORE)


def page_ws():
    ts = json.load(urllib.request.urlopen(CDP + "/json/list", timeout=10))
    p = [t for t in ts if t["type"] == "page"]
    if not p:
        sys.exit("没有 page target，浏览器没起来")
    return p[0]["webSocketDebuggerUrl"]


async def main(a):
    rows = load_store()
    base = len(rows)
    pages = dupe_pages = 0
    got_new = False
    last_cursor = None
    has_more = True
    log = open(os.path.join(HERE, "pages.log"), "a", encoding="utf-8")

    async with websockets.connect(page_ws(), max_size=200 * 1024 * 1024) as ws:
        n = 0
        pend = {}

        async def send(m, p=None):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": m, "params": p or {}}))
            return n

        for m in ("Network.enable", "Page.enable", "Runtime.enable"):
            await send(m)
        await send("Network.setBlockedURLs", {"urls": BLOCKED})

        pend[await send("Runtime.evaluate", {
            "expression": "(function(){var a=[...document.querySelectorAll('a[href^=\"/user/profile/\"]')]"
                          ".filter(x=>x.textContent.trim()==='我')[0];return a?a.getAttribute('href'):null})()",
            "returnByValue": True})] = "own"
        own = None
        t0 = time.time()
        while own is None and time.time() - t0 < 25:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if pend.get(msg.get("id")) == "own":
                pend.pop(msg["id"])
                own = ((msg.get("result") or {}).get("result") or {}).get("value")
        if not own:
            sys.exit("取不到自己的主页链接 —— 登录态可能失效，请重新扫码")
        await send("Page.navigate", {"url": f"https://www.xiaohongshu.com{own}?tab=fav&subTab=note"})

        deadline = time.time() + a.max_minutes * 60
        next_scroll = time.time() + 6
        while time.time() < deadline and has_more:
            if a.target and len(rows) - base >= a.target:
                break
            # 增量模式从列表顶部开始，撞到已知内容即可停——这与全量续跑相反：
            # 全量续跑开头必然是上百页重复，据此停会永远跑不到新数据。
            if a.incremental and dupe_pages >= a.stop_after:
                print(f"连续 {dupe_pages} 页均为已知条目，增量到头", flush=True)
                break
            if a.max_pages and pages >= a.max_pages:
                print(f"达到页数上限 {a.max_pages}，停止", flush=True)
                break
            if time.time() >= next_scroll:
                await send("Runtime.evaluate", {"expression": SCROLL})
                next_scroll = time.time() + (a.gap if got_new else a.fast_gap)
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 1.0))
            except asyncio.TimeoutError:
                continue
            meth = msg.get("method")
            if meth == "Network.responseReceived" and "collect/page" in msg["params"]["response"]["url"]:
                pend[msg["params"]["requestId"]] = "wait"
            elif meth == "Network.loadingFinished" and pend.get(msg["params"]["requestId"]) == "wait":
                rid = msg["params"]["requestId"]
                pend.pop(rid)
                pend[await send("Network.getResponseBody", {"requestId": rid})] = "body"
            elif pend.get(msg.get("id")) == "body":
                pend.pop(msg["id"])
                body = (msg.get("result") or {}).get("body")
                if not body:
                    continue
                try:
                    j = json.loads(body)
                except Exception:
                    continue
                d = j.get("data") or {}
                if j.get("success") is False:
                    print(f"接口失败 code={j.get('code')} msg={str(j.get('msg'))[:60]}", flush=True)
                    if j.get("code") in (-100, 300012):
                        print("判定为登录态失效，停止", flush=True)
                        break
                    continue
                items = d.get("notes") or []
                cur = d.get("cursor")
                if d.get("has_more") is False:
                    has_more = False
                added, now = 0, int(time.time())
                for it in items:
                    nid = it.get("note_id")
                    if not nid:
                        continue
                    if nid not in rows:
                        added += 1
                    rows[nid] = {"note_id": nid, "type": it.get("type"),
                                 "title": it.get("display_title") or "",
                                 "xsec_token": it.get("xsec_token") or "", "token_at": now,
                                 "cover": ((it.get("cover") or {}).get("url_default") or "")}
                pages += 1
                dupe_pages = 0 if added else dupe_pages + 1
                if added:
                    got_new = True
                line = (f"[{time.strftime('%H:%M:%S')}] 第{pages}页 本页{len(items)}条 新增{added} "
                        f"库内{len(rows)} has_more={d.get('has_more')} cursor同上={cur == last_cursor}")
                print(line, flush=True)
                log.write(line + "\n")
                log.flush()
                last_cursor = cur
                if pages % 10 == 0:
                    save_store(rows)

    save_store(rows)
    tp = {}
    for r in rows.values():
        tp[r.get("type")] = tp.get(r.get("type"), 0) + 1
    json.dump({"total": len(rows), "new_last_run": len(rows) - base, "api_pages_last_run": pages,
               "has_more_at_stop": has_more, "last_run": int(time.time()), "types": tp},
              open(STATE, "w"), ensure_ascii=False, indent=2)
    summary = (f"[{time.strftime('%H:%M:%S')}] 结束 库内{len(rows)} 本次新增{len(rows)-base} "
               f"接口页{pages} has_more={has_more}")
    open(os.path.join(HERE, "pages.log"), "a", encoding="utf-8").write(summary + "\n")
    print(f"\n结束：库内 {len(rows)} 条（本次新增 {len(rows) - base}），接口页 {pages}，"
          f"has_more={has_more}，类型 {tp}", flush=True)


ap = argparse.ArgumentParser()
ap.add_argument("--target", type=int, default=0)
ap.add_argument("--max-minutes", type=int, default=60)
ap.add_argument("--idle-stop", type=int, default=0)   # 保留参数但不再用于停机
ap.add_argument("--max-pages", type=int, default=1200)
ap.add_argument("--fast-gap", type=float, default=0.7)
ap.add_argument("--incremental", action="store_true", help="从顶部扫到遇见已知条目为止")
ap.add_argument("--stop-after", type=int, default=3, help="增量模式下连续多少页无新条目即停")
ap.add_argument("--gap", type=float, default=1.6)
asyncio.run(main(ap.parse_args()))
