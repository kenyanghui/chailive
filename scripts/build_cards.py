#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cl2 卡片流构建器：拆页级扁平索引（chapters.js）+ 拆学习页（living.html）。

依赖：merge_build.py 先跑（其会重建 data/，故本脚本必须后跑）。
输入：cfl-work outs（clean 数据）+ scripts/chapters/{chapters,book_chapters}.json + books.meta.json
输出：data/chapters.js（CHAI_CHAPTERS+CHAI_CARDS）+ index.html（从 template-living.html 静态拷贝，拆学习为新首页）
      + build.json 增补两文件 sha256
"""
import hashlib, json, shutil, sys
from collections import Counter
from pathlib import Path

OUTS = Path(__file__).resolve().parent.parent / "raw" / "outs"
CH_DIR = Path(__file__).resolve().parent / "chapters"
SC = Path(__file__).resolve().parent
OUT = Path(__file__).resolve().parent.parent
META = Path(__file__).resolve().parent.parent / "raw" / "books.meta.json"

def sha(b):
    return hashlib.sha256(b).hexdigest()

def main():
    chs = {c["id"]: c for c in json.loads((CH_DIR / "chapters.json").read_text())}
    mods_src = json.loads((CH_DIR / "modules.json").read_text())
    _seen = [cid for m in mods_src for cid in m["chs"]]
    if len(_seen) != len(set(_seen)) or set(_seen) != set(chs):
        sys.exit(f"modules.json 归组对账失败: chapters={len(chs)} grouped={len(_seen)} uniq={len(set(_seen))}")
    bc = {x["id"]: x["ch"] for x in json.loads((CH_DIR / "book_chapters.json").read_text())}
    bt = {b["id"]: b.get("t", "") for b in json.loads(META.read_text())}

    cards = []
    ch_cnt = Counter()
    for sd in sorted(OUTS.iterdir()):
        if not (sd.is_dir() and sd.name.startswith("shard")):
            continue
        for f in sorted((sd / "clean").glob("*.json")):
            d = json.loads(f.read_text())
            bid = str(d["book_id"])
            ch = bc.get(bid, "ch31")
            ch_cnt[ch] += len(d["memoirs"])
            for m in d["memoirs"]:
                lvl = m.get("level") or ""
                g = "A" if lvl.startswith("TF3") else ("B" if lvl.startswith("TF2") else "C")
                ria = any(
                    t.get("flags") and t["flags"]["r"] and t["flags"]["i"] and t["flags"]["a"]
                    for t in (m.get("texts") or [])
                )
                cards.append({
                    "c": ch, "b": bid, "i": m.get("id"),
                    "t": (m.get("topic") or "")[:80],
                    "s": bt.get(bid, "")[:36] or None,
                    "r": (m.get("remark") or "").replace("\r\n", "\n").strip()[:300] or None,
                    "l": lvl or None, "g": g, "x": 1 if ria else 0,
                })
    cards.sort(key=lambda x: (x["c"], str(x["b"]), x["i"] or 0))
    chapters_out = [
        {"id": cid, "name": chs[cid]["name"], "desc": chs[cid].get("desc", ""), "n": ch_cnt.get(cid, 0)}
        for cid in sorted(chs)
    ]
    mods_out = [
        {
            "id": m["id"], "name": m["name"], "hook": m.get("hook", ""),
            "chs": m["chs"],
            "n": sum(ch_cnt.get(cid, 0) for cid in m["chs"]),
        }
        for m in mods_src
    ]
    blob = (
        "window.CHAI_CHAPTERS=" + json.dumps(chapters_out, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c") + ";"
        + "window.CHAI_MODS=" + json.dumps(mods_out, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c") + ";"
        + "window.CHAI_CARDS=" + json.dumps(cards, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c") + ";"
    )
    (OUT / "data" / "chapters.js").write_text(blob)
    shutil.copyfile(SC / "template-living.html", OUT / "index.html")

    bj = OUT / "build.json"
    b = json.loads(bj.read_text())
    b["hashes"]["data/chapters.js"] = sha((OUT / "data" / "chapters.js").read_bytes())
    b["hashes"]["index.html"] = sha((OUT / "index.html").read_bytes())
    bj.write_text(json.dumps(b, ensure_ascii=False, indent=1))
    print(f"cards {len(cards)} across {len(chapters_out)} chapters / {len(mods_out)} modules; chapters.js {len(blob)/1e6:.2f}MB")
    print("modules:", {m["id"]: m["n"] for m in mods_out}, "sum:", sum(m["n"] for m in mods_out))
    print("grade:", Counter(c["g"] for c in cards).most_common())
    print("remark covered:", sum(1 for c in cards if c["r"]), "| ria:", sum(c["x"] for c in cards))

if __name__ == "__main__":
    main()
