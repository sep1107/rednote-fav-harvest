#!/usr/bin/env python3
"""Rebuild the clip queue: everything favorited, minus what's done, minus what's skipped.

Order follows the favorites list (newest first), so anything picked up by an incremental
harvest lands at the head of the queue without special handling.

The queue is derived, never hand-edited — the same reason the ledger is derived. Two
hand-maintained copies of "what still needs doing" would drift apart.
"""
import collections, json, os

HERE = os.path.dirname(os.path.abspath(__file__))


def ids_from(path, key="note_id"):
    out = set()
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                out.add(json.loads(line)[key])
            except Exception:
                out.add(line)                    # 纯 id 列表文件
    return out


done = ids_from(os.path.join(HERE, "out/clipped.jsonl"))
done |= ids_from(os.path.join(HERE, "clipped_ids.txt"))
skip = ids_from(os.path.join(HERE, "skip.jsonl"))

main = {}
for line in open(os.path.join(HERE, "favorites.jsonl"), encoding="utf-8"):
    if line.strip():
        r = json.loads(line)
        main[r["note_id"]] = r

# run2 是一次干净的完整扫描，行序即收藏时间倒序；主库补齐它没覆盖到的
order = []
p2 = os.path.join(HERE, "run2/favorites.jsonl")
if os.path.exists(p2):
    for line in open(p2, encoding="utf-8"):
        if line.strip():
            order.append(json.loads(line)["note_id"])

seen, queue = set(), []
for nid in order:
    if nid in done or nid in skip or nid in seen:
        continue
    seen.add(nid)
    queue.append(main.get(nid) or {"note_id": nid})
for nid, r in main.items():
    if nid not in done and nid not in skip and nid not in seen:
        seen.add(nid)
        queue.append(r)

out = os.path.join(HERE, "batch_rest.jsonl")
with open(out, "w", encoding="utf-8") as f:
    for r in queue:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
c = collections.Counter(r.get("type") for r in queue)
print(f"队列重建：{len(queue)} 条 {dict(c)}｜已处理 {len(done)}，跳过 {len(skip)}，采集库 {len(main)}")
