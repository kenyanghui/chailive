#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chailive 节点端 RIA 提取器（纯 stdlib，确定性，无网络）。

输入：解包的 shard 目录（data/*.json + manifest.json + extract_ria.py）
输出：out/clean/*.json（脱敏后的 RIA 结构）+ out/summary.json（自校验报告）

脱敏红线（与 chai.aibay.asia /hot 管线一致并更严）：
  - 递归删除任意层级的 password / remember_token / email / weixin_code / avatar / logoimg 键
  - 用户对象（user/dianpingyuan/chaishujia）只保留 username/name/city 字符串
  - 删除 radioPwd；HTML 只留白名单结构标签并剥全部属性（a 仅留 http(s) href）
  - 产出再扫 bcrypt/token 指纹，命中即 FAIL（exit 1）
"""
import argparse, hashlib, json, os, re, sys, time, socket
from pathlib import Path

FORBIDDEN_KEYS = {"password", "remember_token", "email", "weixin_code", "avatar", "logoimg"}
DROP_TOP = {"radioPwd"}
FINGERPRINT_RE = re.compile(r"\$2[aby]\$10|remember_token|weixin_code|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# ---------- HTML 净化：白名单结构标签，剥属性，解包 span/div/font ----------
KEEP_TAGS = {"p", "br", "strong", "em", "b", "i", "u", "ul", "ol", "li",
             "table", "thead", "tbody", "tr", "td", "th", "h1", "h2", "h3", "h4",
             "blockquote", "hr"}
UNWRAP_TAGS = {"span", "div", "font", "section", "article", "center", "pre"}
KILL_BLOCKS = re.compile(r"<(script|style|iframe|object|noscript)[^>]*>.*?</\1>|<!--.*?-->", re.S | re.I)
TAG_RE = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)\b[^>]*?(/?)>")
HREF_RE = re.compile(r"""href\s*=\s*["']?(https?://[^\s"']+)""", re.I)


def sanitize_html(s):
    if not s:
        return ""
    out = KILL_BLOCKS.sub("", s)
    def repl(m):
        tag, selfclose = m.group(1).lower(), m.group(2)
        closing = m.group(0).startswith("</")
        if tag in ("embed", "img", "video", "audio", "source", "input", "form", "button"):
            return ""
        if tag == "a" and not closing:
            hm = HREF_RE.search(m.group(0))
            if hm:
                return '<a href="%s">' % hm.group(1)
            return ""
        if tag in UNWRAP_TAGS:
            return ""
        if tag in KEEP_TAGS:
            return m.group(0) if closing else "<%s>" % tag + ("" if selfclose else "")
        return ""
    out = TAG_RE.sub(repl, out)
    out = re.sub(r"<p>(\s|&nbsp;|<br\s*/?>)*</p>", "", out)
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n\s*\n+", "\n", out)
    return out.strip()


def scrub(obj, stats):
    """递归脱敏：删禁键 + 白名单化用户对象。"""
    if isinstance(obj, dict):
        clean = {}
        for k, v in obj.items():
            if k in FORBIDDEN_KEYS:
                stats["forbidden_key_removed"] = stats.get("forbidden_key_removed", 0) + 1
                continue
            if k in DROP_TOP:
                stats["radiopwd_dropped"] = stats.get("radiopwd_dropped", 0) + 1
                continue
            if k in ("user", "dianpingyuan", "chaishujia") and isinstance(v, dict):
                nm = v.get("username") or v.get("name") or ""
                if EMAIL_RE.search(nm):
                    stats["username_email_masked"] = stats.get("username_email_masked", 0) + 1
                    nm = "[email]"
                city = v.get("city") or ""
                clean[k] = {"username": nm, "city": city} if nm else {}
                stats["user_obj_minimized"] = stats.get("user_obj_minimized", 0) + 1
                continue
            clean[k] = scrub(v, stats)
        return clean
    if isinstance(obj, list):
        return [scrub(x, stats) for x in obj]
    if isinstance(obj, str):
        if EMAIL_RE.search(obj):
            stats["email_masked"] = stats.get("email_masked", 0) + 1
            return EMAIL_RE.sub("[email]", obj)
        return obj
    return obj


def person_of(m):
    cs = (m.get("program") or {}).get("chaishujia") or {}
    return {"username": cs.get("username") or "", "city": cs.get("city") or ""}


def club_of(prog):
    act = prog.get("activity") or {}
    rud = act.get("rudder") or {}
    name = rud.get("name") or act.get("name") or ""
    city = rud.get("city") or act.get("city") or ""
    return {"name": name, "city": city} if (name or city) else {}


def book_of(prog, fallback_id):
    b = prog.get("book") or {}
    tags = [t.strip() for t in re.split(r"[,，]", b.get("tags") or "") if t.strip()]
    return {
        "id": b.get("id") or fallback_id,
        "title": b.get("title") or "",
        "author": b.get("author") or "",
        "translator": b.get("translator") or "",
        "publisher": b.get("publisher") or "",
        "pubdate": b.get("pubdate") or "",
        "isbn": b.get("isbn") or "",
        "tags": tags[:12],
        "memCount": b.get("memCount"),
    }


def text_item(t):
    q, e, i = (sanitize_html(t.get(x) or "") for x in ("quote", "explains", "interaction"))
    joined = e + "\n" + i
    return {
        "id": t.get("id"),
        "quote": q or None, "explains": e or None, "interaction": i or None,
        "flags": {
            "r": bool(q), "i": bool(e), "a": bool(i),
            "a1": "【A1" in joined, "a2": "【A2" in joined, "a3": "【A3" in joined,
        },
    }


def clean_memoir(m, stats, book_fallback_id):
    prog = m.get("program") or {}
    ratings = m.get("ratings") or []
    texts = [text_item(t) for t in (m.get("texts") or [])]
    if any(f["flags"]["a1"] or f["flags"]["a2"] or f["flags"]["a3"] for f in texts):
        stats["memoirs_with_a_steps"] = stats.get("memoirs_with_a_steps", 0) + 1
    return {
        "id": m.get("id"),
        "topic": prog.get("topic") or m.get("topic") or "",
        "learn_goal": prog.get("learn_goal") or "",
        "remark": prog.get("remark") or "",
        "level": prog.get("level") or "",
        "duration": prog.get("duration"),
        "status": m.get("status"),
        "type": m.get("type"),
        "chaishujia": person_of(m),
        "club": club_of(prog),
        "book": book_of(prog, book_fallback_id),
        "prologue": sanitize_html(m.get("prologue") or "") or None,
        "ratings_count": len(ratings),
        "texts": texts,
        "created_at": m.get("created_at"),
        "updated_at": m.get("updated_at"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".", help="shard 解包目录（含 data/ 与 manifest.json）")
    ap.add_argument("--out", default="out", help="输出目录")
    a = ap.parse_args()
    root, outdir = Path(a.dir), Path(a.out)
    (outdir / "clean").mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    manifest = json.loads((root / "manifest.json").read_text())
    data_dir = root / "data"
    stats, files_ok, sha_fail, parse_fail = {}, 0, [], []
    total_memoirs = total_texts = 0
    out_md5 = {}
    import hashlib as H

    for name in manifest["files"]:
        p = data_dir / name
        if not p.exists():
            parse_fail.append([name, "missing"])
            continue
        if H.md5(p.read_bytes()).hexdigest() != manifest["sha_expect"][name]:
            sha_fail.append(name)
            continue
        try:
            d = json.loads(p.read_text())
        except Exception as ex:
            parse_fail.append([name, "json:" + str(ex)[:60]])
            continue
        if isinstance(d, dict) and "texts" in d:
            ms = [d]
        elif isinstance(d, dict):
            ms = d.get("memoirs") or []
        else:
            ms = d
        bid = None
        try:
            bid = int(Path(name).stem)
        except ValueError:
            bid = ((ms[0].get("program") or {}).get("book") or {}).get("id") if ms else None
        file_stats = {}
        cleaned = [clean_memoir(m, file_stats, bid) for m in ms]
        cleaned = scrub(cleaned, stats)  # 兜底二道脱敏（含 program 残余）
        payload = {"file": name, "book_id": bid, "memoirs": cleaned}
        blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if FINGERPRINT_RE.search(blob):
            print(f"FINGERPRINT-HIT {name}", file=sys.stderr)
            parse_fail.append([name, "fingerprint"])
            continue
        (outdir / "clean" / name).write_text(blob)
        out_md5[name] = H.md5(blob.encode()).hexdigest()
        for k, v in file_stats.items():
            stats[k] = stats.get(k, 0) + v
        files_ok += 1
        total_memoirs += len(cleaned)
        total_texts += sum(1 for c in cleaned for _ in c["texts"])

    summary = {
        "shard": manifest["shard"],
        "node": {"host": socket.gethostname(), "python": sys.version.split()[0]},
        "files_ok": files_ok,
        "files_fail": len(parse_fail) + len(sha_fail),
        "sha_fail": sha_fail,
        "parse_fail": parse_fail,
        "memoirs": total_memoirs,
        "texts": total_texts,
        "sanitize": stats,
        "bytes_out": sum((outdir / "clean" / n).stat().st_size for n in out_md5),
        "out_md5": out_md5,
        "secs": round(time.time() - t0, 1),
    }
    (outdir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False))
    ok = not sha_fail and not parse_fail
    print(f"shard{manifest['shard']} @{socket.gethostname()}: {files_ok} files, "
          f"{total_memoirs} memoirs, {total_texts} texts, {summary['bytes_out']/1e6:.1f}MB out, "
          f"{summary['secs']}s -> {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
