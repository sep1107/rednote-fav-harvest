#!/usr/bin/env python3
"""Minimal CDP client over the local debugging port. Read/drive only, writes nothing but screenshots."""
import asyncio, base64, json, sys, urllib.request
import websockets

def page_ws():
    ts = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=10))
    pages = [t for t in ts if t["type"] == "page"]
    if not pages:
        raise SystemExit("no page target")
    return pages[0]["webSocketDebuggerUrl"], pages[0]

async def call(method, params=None, timeout=60):
    url, _ = page_ws()
    async with websockets.connect(url, max_size=80 * 1024 * 1024, open_timeout=20) as ws:
        await ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
            if msg.get("id") == 1:
                if "error" in msg:
                    raise SystemExit("CDP error: " + json.dumps(msg["error"], ensure_ascii=False))
                return msg.get("result", {})

def main():
    cmd = sys.argv[1]
    if cmd == "targets":
        for t in json.load(urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=10)):
            print(t["type"], "|", t["title"][:60], "|", t["url"][:90])
    elif cmd == "eval":
        r = asyncio.run(call("Runtime.evaluate", {
            "expression": sys.argv[2], "returnByValue": True, "awaitPromise": True}))
        res = r.get("result", {})
        print(json.dumps(res.get("value", res.get("description")), ensure_ascii=False, indent=2)[:12000])
    elif cmd == "nav":
        asyncio.run(call("Page.navigate", {"url": sys.argv[2]}))
        print("navigated:", sys.argv[2])
    elif cmd == "shot":
        r = asyncio.run(call("Page.captureScreenshot", {"format": "png"}))
        open(sys.argv[2], "wb").write(base64.b64decode(r["data"]))
        print("saved", sys.argv[2])
    elif cmd == "cookies":
        r = asyncio.run(call("Network.getCookies", {}))
        names = sorted({c["name"] for c in r.get("cookies", [])})
        print("cookie 数:", len(r.get("cookies", [])), "| 名称:", ", ".join(names[:25]))
    elif cmd == "raw":
        params = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        print(json.dumps(asyncio.run(call(sys.argv[2], params)), ensure_ascii=False)[:4000])
    else:
        raise SystemExit("usage: cdp.py targets|eval <js>|nav <url>|shot <file>|cookies|raw <method> [json]")

main()
