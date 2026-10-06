#!/usr/bin/env python3
"""会话存档分析器（考古流程脚本化，2026-10-07 沉淀）

配合 decrypt_export.py 使用：导出产物在 ../解析输出/会话存档/NNN_标题.md，
本脚本把「关键词命中定位 → 体量排序 → 单会话结构统计」三步机械活一次跑完，
替代此前每轮手敲的 grep -c / ls -S / wc / grep -c 标记 组合。
语义判读（摩擦点、为什么这轮浪费）仍归人/子代理，本脚本只出候选与计数。

用法：
  python3 analyze_sessions.py index <正则1> [<正则2> ...] [--top N] [--dir DIR]
      跨全部存档做 pattern 命中计数（| 连接为或），按命中数降序输出
      「命中数 行数 字节 文件名」，默认前 30 个。定位相关会话用。
  python3 analyze_sessions.py stats <文件1> [<文件2> ...] [--dir DIR]
      单会话结构统计：字节/行数/用户轮数/助手轮数/工具块数/工具名频次
      ＋每个用户轮的起始行号（供 Read offset/limit 分窗精读取锚）。
  python3 analyze_sessions.py top [--dir DIR] [--min-kb K]
      全存档按字节降序（含轮数），先粗筛"大会话"。--min-kb 过滤小文件。

存档格式约定（decrypt_export.py 产物）：
  **🧑 用户** / **🤖 助手** 行首标记轮次；[工具调用: Name(args), ...] 行记工具块。
"""

import re
import sys
from collections import Counter
from pathlib import Path

USER_RE = re.compile(r"^\*\*🧑 用户\*\*")
ASSIST_RE = re.compile(r"^\*\*🤖 助手\*\*")
TOOL_RE = re.compile(r"^\[工具调用: (.*)\]")
TOOL_NAME_RE = re.compile(r"(?:^|, )([A-Za-z_][A-Za-z0-9_]*)\(")
META_RE = re.compile(r"创建: ([\d\- :]+) · 更新: ([\d\- :]+)")


def archive_dir(cli=None):
    if cli:
        return Path(cli)
    return Path(__file__).resolve().parent.parent / "解析输出" / "会话存档"


def cmd_index(args):
    pats, top, dirp = [], 30, None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--top":
            top = int(args[i + 1]); i += 2; continue
        if a == "--dir":
            dirp = args[i + 1]; i += 2; continue
        pats.append(a); i += 1
    rx = re.compile("|".join(pats))
    d = archive_dir(dirp)
    rows = []
    for f in sorted(d.glob("*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        hits = sum(len(rx.findall(line)) for line in text.splitlines())
        if hits:
            rows.append((hits, text.count("\n") + 1, len(text.encode("utf-8")), f.name))
    rows.sort(reverse=True)
    print(f"# index：pattern={'|'.join(pats)}  目录={d}  命中文件 {len(rows)} 个，列前 {min(top, len(rows))}")
    for hits, lines, size, name in rows[:top]:
        print(f"{hits:>6} 命中 {lines:>6} 行 {size / 1024:>7.1f}KB  {name}")
    return 0


def stats_one(f: Path):
    text = f.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    tool_counter = Counter()
    user_line_nums, blocks = [], 0
    meta = META_RE.search(text[:2000])
    for n, line in enumerate(lines, 1):
        if USER_RE.match(line):
            user_line_nums.append(n)
        elif ASSIST_RE.match(line):
            pass
        m = TOOL_RE.match(line)
        if m:
            blocks += 1
            tool_counter.update(TOOL_NAME_RE.findall(m.group(1)))
    assistants = sum(1 for line in lines if ASSIST_RE.match(line))
    print(f"\n=== {f.name} ===")
    print(f"字节 {len(text.encode('utf-8')) / 1024:.1f}KB｜行数 {len(lines)}｜"
          f"用户轮 {len(user_line_nums)}｜助手轮 {assistants}｜工具块 {blocks}"
          + (f"｜创建 {meta.group(1)} 更新 {meta.group(2)}" if meta else ""))
    if tool_counter:
        tc = "，".join(f"{k}×{v}" for k, v in tool_counter.most_common(15))
        print(f"工具名频次：{tc}")
    if user_line_nums:
        shown = user_line_nums if len(user_line_nums) <= 25 else user_line_nums[:25]
        print(f"用户轮起始行：{shown}" + ("…(截断)" if len(user_line_nums) > 25 else ""))
    return 0


def cmd_stats(args):
    dirp, files = None, []
    i = 0
    while i < len(args):
        if args[i] == "--dir":
            dirp = args[i + 1]; i += 2; continue
        files.append(args[i]); i += 1
    d = archive_dir(dirp)
    rc = 0
    for name in files:
        f = Path(name) if "/" in name else d / name
        if not f.exists():
            cands = sorted(d.glob(f"{name}*.md")) if not name.endswith(".md") else []
            if cands:
                f = cands[0]
            else:
                print(f"文件不存在：{f}", file=sys.stderr); rc = 2; continue
        stats_one(f)
    return rc


def cmd_top(args):
    dirp, minkb = None, 0
    i = 0
    while i < len(args):
        if args[i] == "--dir":
            dirp = args[i + 1]; i += 2; continue
        if args[i] == "--min-kb":
            minkb = float(args[i + 1]); i += 2; continue
        i += 1
    d = archive_dir(dirp)
    rows = []
    for f in d.glob("*.md"):
        size = f.stat().st_size
        if size / 1024 >= minkb:
            rows.append((size, f.name))
    rows.sort(reverse=True)
    print(f"# top：目录={d}，共 {len(rows)} 个 ≥{minkb:.0f}KB（降序，含结构统计）")
    for size, name in rows:
        stats_one(d / name)
    return 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("index", "stats", "top"):
        print(__doc__)
        return 1
    return {"index": cmd_index, "stats": cmd_stats, "top": cmd_top}[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
