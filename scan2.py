#!/usr/bin/env python3
"""扫描 mem.bin 中的 x'<hex>' raw key 模式"""
import re

data = open('/tmp/trae_export/mem.bin', 'rb').read()
print(f'mem.bin: {len(data)/1024/1024:.0f}MB')
found = set()
for m in re.finditer(rb"x'([0-9a-fA-F]{64,192})'", data):
    found.add(m.group(1)[:64].decode())
# 也搜裸 PRAGMA 语句形态
for m in re.finditer(rb"PRAGMA key\s*=\s*[\"']?x'([0-9a-fA-F]{64})'", data):
    found.add(m.group(1).decode())
cands = sorted(found)
open('/tmp/trae_export/candidates.txt', 'w').write('\n'.join(cands))
print(f'候选密钥: {len(cands)} 个')
for c in cands[:10]:
    print(' ', c)
