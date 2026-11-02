#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chailive 矩阵切分器：把 chaishu-hot raw 拆页按体积贪心装箱成 N 片，打包分发。

每片 tar.gz 内含：data/*.json（拆页原始文件）+ extract_ria.py（节点端提取器）+ manifest.json。
节点解包后只需 python3（纯 stdlib），跑完回传 out 片 tar.gz。
"""
import argparse, json, os, shutil, tarfile, hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="/root/chaishu-hot/raw/memoirs")
    ap.add_argument("--work", default="/tmp/octopus/cfl-work")
    ap.add_argument("--shards", type=int, default=6)
    ap.add_argument("--extract", default=str(Path(__file__).resolve().parent / "extract_ria.py"))
    a = ap.parse_args()

    raw, work = Path(a.raw), Path(a.work)
    shards_dir, pkgs_dir = work / "shards", work / "pkgs"
    for d in (shards_dir, pkgs_dir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    files = []
    for f in sorted(raw.glob("*.json")):
        sz = f.stat().st_size
        if sz > 200:
            files.append((f.name, sz))
    total = sum(s for _, s in files)
    print(f"有效拆页文件 {len(files)} 个，共 {total/1e6:.1f}MB，装 {a.shards} 箱")

    # 贪心装箱：大到小，放进最轻箱
    bins = [[] for _ in range(a.shards)]
    loads = [0] * a.shards
    for name, sz in sorted(files, key=lambda x: -x[1]):
        k = loads.index(min(loads))
        bins[k].append((name, sz))
        loads[k] += sz

    manifest_all = {}
    for k, items in enumerate(bins):
        sdir = shards_dir / f"shard{k}"
        (sdir / "data").mkdir(parents=True)
        names = []
        for name, sz in items:
            shutil.copy2(raw / name, sdir / "data" / name)
            names.append(name)
        shard_manifest = {
            "shard": k,
            "files": names,
            "bytes": loads[k],
            "sha_expect": {},
        }
        # 提取器运行时的自校验清单：文件名 + md5（节点跑完逐项对账）
        for name in names:
            h = hashlib.md5((raw / name).read_bytes()).hexdigest()
            shard_manifest["sha_expect"][name] = h
        (sdir / "manifest.json").write_text(json.dumps(shard_manifest, ensure_ascii=False))
        shutil.copy2(a.extract, sdir / "extract_ria.py")

        pkg = pkgs_dir / f"shard{k}.tar.gz"
        with tarfile.open(pkg, "w:gz") as tf:
            tf.add(sdir / "data", arcname="data")
            tf.add(sdir / "manifest.json", arcname="manifest.json")
            tf.add(sdir / "extract_ria.py", arcname="extract_ria.py")
        manifest_all[f"shard{k}"] = {"files": len(names), "raw_bytes": loads[k], "pkg_bytes": pkg.stat().st_size}
        print(f"shard{k}: {len(names)} 文件 raw {loads[k]/1e6:.1f}MB -> pkg {pkg.stat().st_size/1e6:.1f}MB")

    (work / "manifest-all.json").write_text(json.dumps(manifest_all, ensure_ascii=False, indent=1))
    print("manifest-all.json 写入", work)


if __name__ == "__main__":
    main()
