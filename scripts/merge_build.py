#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chailive 汇聚构建器（reducer = loong-dev）。

输入：/tmp/octopus/cfl-work/outs/shard{0..N}/（各节点回传的 clean/*.json + summary.json）
输出：/root/chailive/{index.html, data/<bookId>.js, stats.json, build.json}

职责：
  1. 收块校验：逐文件 md5 对账 summary.out_md5；计数断言（1713 文件 / 19262 拆页）
  2. 按书重组：memoir 内重复的 book 元数据上提去重（体积省 ~1/3）
  3. 终检脱敏：合并体全量过指纹正则（bcrypt/token/email），命中即 FAIL 退出
  4. 构建产物：data/<id>.js 懒加载分片 + L1 书目索引内嵌 index.html（模板注入）
  5. 确定性：排序键固定、无时间戳；build.json 记录全量 sha256 供双跑一致性核对
"""
import argparse, hashlib, json, re, shutil, sys
from collections import Counter, defaultdict
from pathlib import Path

FINGERPRINT = re.compile(r"\$2[aby]\$10|remember_token|weixin_code|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def sha(s):
    return hashlib.sha256(s).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/octopus/cfl-work")
    ap.add_argument("--out", default="/root/chailive")
    ap.add_argument("--books", default="/root/chaishu-hot/raw/books.json")
    ap.add_argument("--covers", default="/root/chaishu-hot/raw/covers-report.json")
    ap.add_argument("--expect-files", type=int, default=1713)
    ap.add_argument("--expect-memoirs", type=int, default=19262)
    a = ap.parse_args()

    work, out = Path(a.work), Path(a.out)
    outs = work / "outs"
    shard_dirs = sorted(d for d in outs.iterdir() if d.is_dir() and d.name.startswith("shard"))
    if not shard_dirs:
        sys.exit("no shard outputs under " + str(outs))

    # ---- 1. 收块 + md5 对账 ----
    per_file = {}          # book_id -> payload
    total_memoirs = 0
    cs_counter = Counter()
    club_counter = Counter()
    lvl_counter = Counter()
    ria_full = 0
    problems = []
    for sd in shard_dirs:
        summary = json.loads((sd / "summary.json").read_text())
        if summary.get("sha_fail") or summary.get("parse_fail"):
            problems.append((sd.name, summary["sha_fail"], summary["parse_fail"]))
        clean = sd / "clean"
        for name, expect_md5 in summary["out_md5"].items():
            blob = (clean / name).read_bytes()
            if hashlib.md5(blob).hexdigest() != expect_md5:
                problems.append((sd.name, name, "md5-mismatch-on-reducer"))
                continue
            payload = json.loads(blob)
            bid = str(payload["book_id"])
            per_file[bid] = payload
            total_memoirs += len(payload["memoirs"])
    if problems:
        for p in problems[:10]:
            print("PROBLEM:", p)
        sys.exit("block verification failed")
    if len(per_file) != a.expect_files:
        sys.exit(f"file count {len(per_file)} != expect {a.expect_files}")
    if total_memoirs != a.expect_memoirs:
        sys.exit(f"memoir count {total_memoirs} != expect {a.expect_memoirs}")
    print(f"blocks OK: {len(per_file)} books, {total_memoirs} memoirs")

    # ---- 2. 按书重组（book 元数据上提去重）----
    books_out = {}
    for bid, payload in per_file.items():
        meta = None
        for m in payload["memoirs"]:
            if m.get("book"):
                meta = m["book"]
                break
        memoirs = []
        for m in payload["memoirs"]:
            m.pop("book", None)
            cs = m.get("chaishujia") or {}
            if cs.get("username"):
                cs_counter[cs["username"]] += 1
            cl = m.get("club") or {}
            if cl.get("name"):
                club_counter[cl["name"]] += 1
            if m.get("level"):
                lvl_counter[m["level"]] += 1
            fl = [t.get("flags") for t in (m.get("texts") or [])]
            if any(f and f["r"] and f["i"] and f["a"] for f in fl):
                ria_full += 1
                m["ria"] = True
            memoirs.append(m)
        books_out[bid] = {"book": meta or {"id": bid, "title": f"#{bid}"}, "memoirs": memoirs}

    # ---- 3. 终检脱敏（合并体全量）----
    for bid, bo in books_out.items():
        blob = json.dumps(bo, ensure_ascii=False, separators=(",", ":"))
        hit = FINGERPRINT.search(blob)
        if hit:
            sys.exit(f"FINGERPRINT in book {bid}: ...{blob[max(0,hit.start()-40):hit.end()+20]}...")
    print("sanity: fingerprint scan clean")

    # ---- 4. 构建产物（data 分片 + topics 索引 + L1）----
    data_dir = out / "data"
    topics = []
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True)
    have_cover = set()
    cov_dir = Path("/root/gh-chaishu/public/hot/covers")
    if cov_dir.exists():
        have_cover = {p.stem for p in cov_dir.glob("*.jpg")}
    src_books = json.loads(Path(a.books).read_text())
    if isinstance(src_books, dict):
        src_books = src_books.get("books", [])

    l1 = {}
    book_meta_by_id = {}
    for sb in src_books:
        bid = str(sb.get("id"))
        rec = {
            "id": bid, "title": sb.get("title") or "", "author": sb.get("author") or "",
            "translator": sb.get("translator") or "", "publisher": sb.get("publisher") or "",
            "pubdate": sb.get("pubdate") or "",
            "tags": [t.strip() for t in re.split(r"[,，]", sb.get("tags") or "") if t.strip()][:4],
            "src_mc": int(sb.get("memCount") or 0),
            "cov": 1 if bid in have_cover else 0,
        }
        l1[bid] = rec
        book_meta_by_id[bid] = rec
    for bid, bo in sorted(books_out.items()):
        rec = l1.get(bid)
        if not rec:
            rec = {"id": bid, "title": bo["book"].get("title") or f"#{bid}", "author": bo["book"].get("author") or "",
                   "translator": "", "publisher": "", "pubdate": "", "tags": [],
                   "src_mc": 0, "cov": 0}
            l1[bid] = rec
        lvls = sorted({m.get("level") for m in bo["memoirs"] if m.get("level")})
        rec["nc"] = len(bo["memoirs"])
        rec["ria"] = sum(1 for m in bo["memoirs"] if m.get("ria"))
        rec["lv"] = (lvls[0] + (("~" + lvls[-1]) if len(lvls) > 1 else "")) if lvls else ""
        for m in bo["memoirs"]:
            topics.append({
                "b": bid, "i": m.get("id"), "t": (m.get("topic") or "")[:60],
                "l": m.get("level") or "", "c": (m.get("chaishujia") or {}).get("username") or "",
                "g": 1 if m.get("ria") else 0,
            })

        # 大书分片：紧凑 idx（全量拆页目录，含 part 号）+ 正文按 ~1.5MB 切 part；part1=data/<id>.js
        ser = [json.dumps(m, ensure_ascii=False, separators=(",", ":")) for m in bo["memoirs"]]
        parts, cur, cur_bytes = [], [], 0
        for s in ser:
            cur.append(s)
            cur_bytes += len(s)
            if cur_bytes > 1_500_000:
                parts.append(cur)
                cur, cur_bytes = [], 0
        if cur or not parts:
            parts.append(cur)
        pb, acc, pnum = [], 0, []
        for pi, p in enumerate(parts, 1):
            acc += len(p)
            pb.append(acc)
            pnum.extend([pi] * len(p))
        idx = [
            {"i": m.get("id"), "t": (m.get("topic") or "")[:60], "l": m.get("level") or "",
             "c": (m.get("chaishujia") or {}).get("username") or "",
             "g": 1 if m.get("ria") else 0, "p": pnum[k]}
            for k, m in enumerate(bo["memoirs"])
        ]
        head = json.dumps(
            {"book": bo["book"], "np": len(parts), "pb": pb, "idx": idx},
            ensure_ascii=False, separators=(",", ":"),
        ).replace("<", "\\u003c")
        for pi, p in enumerate(parts, 1):
            blob = ("[" + ",".join(p) + "]").replace("<", "\\u003c")
            if pi == 1:
                body = 'window.CHAI_DATA=window.CHAI_DATA||{};CHAI_DATA["' + bid + '"]=' + head[:-1] + ',"ms":' + blob + "};"
                (data_dir / f"{bid}.js").write_text(body)
            else:
                body = ('(window.CHAI_PD=window.CHAI_PD||{})["' + bid + "_" + str(pi) + '"]=' + blob + ";")
                (data_dir / f"{bid}.p{pi}.js").write_text(body)
        # 用净化后的 book meta 修正 L1（title/author 以源头 books.json 为准，缺则回填）
        if not rec["title"] or rec["title"] == f"#{bid}":
            rec["title"] = bo["book"].get("title") or rec["title"]

    # 封面随仓自包含（零外部依赖灵魂）：covers/<id>.jpg
    src_cov = Path("/root/gh-chaishu/public/hot/covers")
    dst_cov = out / "covers"
    if dst_cov.exists():
        shutil.rmtree(dst_cov)
    if src_cov.exists():
        shutil.copytree(src_cov, dst_cov)
        print(f"covers: {len(list(dst_cov.glob('*.jpg')))} copied")

    # ---- 5. L1 注入模板 + 产物 ----
    tmpl = Path(__file__).resolve().parent.joinpath("template.html").read_text()
    stats = {
        "books": len(l1),
        "booksWithMemoirs": len(books_out),
        "memoirs": total_memoirs,
        "riaComplete": ria_full,
        "chaishujia": len(cs_counter),
        "clubs": len(club_counter),
        "topChaishujia": [[k, v] for k, v in cs_counter.most_common(12)],
        "topClubs": [[k, v] for k, v in club_counter.most_common(12)],
        "levels": dict(lvl_counter.most_common()),
    }
    l1_blob = json.dumps(l1, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    topics_blob = json.dumps(topics, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    (data_dir / "topics.js").write_text(
        "window.CHAI_TOPICS=" + topics_blob + ";window.CHAI_DATA=window.CHAI_DATA||{};CHAI_DATA._topics=1;"
    )
    html_out = tmpl.replace("__STATS__", json.dumps(stats, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c"))
    html_out = html_out.replace("__STATS_BOOKS__", str(stats["books"])).replace("__STATS_MEMOIRS__", str(stats["memoirs"]))
    html_out = html_out.replace("__BOOKS__", l1_blob)
    (out / "index.html").write_text(html_out)

    # 确定性指纹：全产物 sha256
    hashes = {"index.html": sha((out / "index.html").read_bytes())}
    for f in sorted(data_dir.glob("*.js")):
        hashes[f"data/{f.name}"] = sha(f.read_bytes())
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1))
    (out / "build.json").write_text(json.dumps({"hashes": hashes, "stats": stats}, ensure_ascii=False, indent=1))
    data_mb = sum(f.stat().st_size for f in data_dir.glob("*.js")) / 1e6
    biggest = sorted(((f.stat().st_size, f.name) for f in data_dir.glob("*.js")), reverse=True)[:3]
    print(f"build OK: index.html {len(html_out)/1e6:.2f}MB, data {len(hashes)-1} files {data_mb:.1f}MB")
    print("biggest:", [(f'{n} {s/1e6:.1f}MB') for s, n in biggest])
    print(f"L1 books {stats['books']} | riaComplete {ria_full} | cs {stats['chaishujia']} | clubs {stats['clubs']}")


if __name__ == "__main__":
    main()
