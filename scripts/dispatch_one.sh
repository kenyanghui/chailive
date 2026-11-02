#!/usr/bin/env bash
# chailive 单节点派发器：pkg 上行 -> 节点提取 -> out 回传解包 -> 节点清场
# 用法: dispatch_one.sh <ssh-target> <shardN>
set -euo pipefail
SSH="$1"; N="$2"
W=/tmp/octopus/cfl-work
RD=/tmp/cfl-$N
OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new"

ssh $OPTS "$SSH" "python3 -c \"import shutil,os;shutil.rmtree('$RD',ignore_errors=True);os.makedirs('$RD')\""
scp $OPTS -q "$W/pkgs/$N.tar.gz" "$SSH:$RD/$N.tar.gz"
ssh $OPTS "$SSH" "cd '$RD' && tar xzf $N.tar.gz && python3 extract_ria.py --dir . --out out && tar czf out.tar.gz -C out clean summary.json"
scp $OPTS -q "$SSH:$RD/out.tar.gz" "$W/outs/$N-out.tar.gz"
mkdir -p "$W/outs/$N"
tar xzf "$W/outs/$N-out.tar.gz" -C "$W/outs/$N"
ssh $OPTS "$SSH" "python3 -c \"import shutil;shutil.rmtree('$RD',ignore_errors=True)\""
echo "NODE-DONE $N ($(du -sb "$W/outs/$N/clean" | cut -f1) bytes clean)"
