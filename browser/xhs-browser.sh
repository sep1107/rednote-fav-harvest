#!/bin/bash
PROF="$HOME/snap/chromium/common/xhs-profile"
# UA 去掉 Headless 并对齐真实 Chrome 版本；语言改中文；补软件 WebGL（风控指纹要用）
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
exec chromium \
  --headless=new \
  --remote-debugging-port=9222 \
  --remote-allow-origins=* \
  --user-data-dir="$PROF" \
  --user-agent="$UA" \
  --lang=zh-CN \
  --accept-lang=zh-CN,zh;q=0.9,en;q=0.8 \
  --enable-unsafe-swiftshader \
  --disable-blink-features=AutomationControlled \
  --window-size=1600,1000 \
  --no-first-run --no-default-browser-check \
  --disable-gpu \
  "https://www.xiaohongshu.com/explore"
