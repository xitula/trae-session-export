#!/usr/bin/env python3
"""Trae CN database.db 一键解密 + 按项目导出会话
用法:
  python3 decrypt_export.py --db /path/to/database.db \
      --project <你的项目路径子串> --out /path/to/输出目录
依赖: pip install --user --break-system-packages pycryptodome
说明: 密钥为 Trae CN 确定性密钥(见 README)。输出: 解密库 decrypted.db + 会话索引.md + 会话存档/*.md
"""
import argparse, bisect, datetime, json, os, re, sqlite3
from Crypto.Cipher import AES

KEY = '3605f6691095a993f03d5009c918352ef5be31ae31e8f000212b81ff058da773'
PAGE, OFF = 4096, 4016  # 页大小 / IV偏移(reserve=80: iv16+hmac-sha512 64)

def decrypt_db(src, dst):
    sz = os.path.getsize(src)
    npages = sz // PAGE
    out = open(dst, 'wb')
    with open(src, 'rb') as f:
        page = f.read(PAGE)  # 页1: 前16字节为salt(解密后替换为SQLite头)
        iv = page[OFF:OFF+16]
        dec = AES.new(bytes.fromhex(KEY), AES.MODE_CBC, iv).decrypt(page[16:OFF])
        out.write(b'SQLite format 3\x00' + dec + b'\x00' * (PAGE - OFF))
        for n in range(1, npages):
            page = f.read(PAGE)
            if len(page) < PAGE:
                break
            iv = page[OFF:OFF+16]
            dec = AES.new(bytes.fromhex(KEY), AES.MODE_CBC, iv).decrypt(page[:OFF])
            out.write(dec + b'\x00' * (PAGE - OFF))
            if n % 20000 == 0:
                print(f'  解密 {n}/{npages}')
    out.close()
    return dst

def ts(sec):
    try:
        return datetime.datetime.fromtimestamp(int(sec)).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return '?'

def tool_label(t):
    """工具调用名＋参数摘要；兼容 function / function_call 两种格式"""
    fn = t.get('function') or t.get('function_call') or {}
    name = fn.get('name', '?')
    args = fn.get('arguments')
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = None
    if isinstance(args, dict):
        for k in ('command', 'file_path', 'pattern', 'query', 'path', 'description', 'prompt'):
            v = args.get(k)
            if isinstance(v, str) and v:
                return f'{name}({v.split(chr(10), 1)[0].strip()[:60]})'
    return name

def msg_text(m):
    role = m.get('role', '?')
    c = m.get('content')
    parts = []
    if isinstance(c, list):
        for item in c:
            if isinstance(item, dict) and item.get('type') == 'text' and item.get('text'):
                parts.append(item['text'])
    elif isinstance(c, str) and c:
        parts.append(c)
    tc = m.get('tool_calls')
    tools = []
    if tc:
        try:
            tools = [tool_label(t) for t in tc]
        except Exception:
            pass
    if role == 'tool':
        return None
    txt = '\n\n'.join(parts).strip()
    if tools:
        txt = (txt + ('\n\n' if txt else '') + f'[工具调用: {", ".join(tools)}]').strip()
    return role, txt

def export_sessions(db, project_sub, outdir):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    rows = con.execute("SELECT id, project_id, absolute_path FROM project WHERE absolute_path LIKE ?",
                       (f'%{project_sub}%',)).fetchall()
    if not rows:
        print(f'未找到项目: {project_sub}'); return
    pid, proj_id, path = rows[0]
    print(f'项目: {path} (project_id={proj_id})')
    arc = os.path.join(outdir, '会话存档')
    os.makedirs(arc, exist_ok=True)
    sessions = con.execute(
        "SELECT session_id, session_title, created_at, updated_at, deleted_at "
        "FROM chat_session WHERE project_id=? ORDER BY created_at", (proj_id,)).fetchall()
    print(f'会话总数: {len(sessions)}')
    index, empty = [], 0
    written = set()
    sids = {sid for sid, *_ in sessions}
    for i, (sid, title, ca, ua, da) in enumerate(sessions, 1):
        lines = [f'# {title or "(无标题)"}', '',
                 f'> 会话ID: {sid} · 创建: {ts(ca)} · 更新: {ts(ua)}' + (' · ⚠️ 已删除' if da else ''), '']
        count = 0
        for mjson, _ in con.execute(
                "SELECT messages, created_at FROM history_v2 WHERE session_id=? ORDER BY id", (sid,)):
            try:
                msgs = json.loads(mjson)
                raw = msgs.get('raw_messages', []) if isinstance(msgs, dict) else (msgs or [])
            except Exception:
                continue
            for m in raw:
                r = msg_text(m)
                if not r:
                    continue
                role, txt = r
                if not txt:
                    continue
                label = '🧑 用户' if role == 'user' else ('🤖 助手' if role == 'assistant' else role)
                lines += [f'**{label}**', '', txt, '']
                count += 1
        if count == 0:
            empty += 1
            continue
        safe = re.sub(r'[\\/:*?"<>|\n]', '_', (title or f'会话{i}'))[:60] or f'会话{i}'
        fname = f'{i:03d}_{safe}.md'
        open(os.path.join(arc, fname), 'w').write('\n'.join(lines))
        written.add(fname)
        index.append(f'| {i:03d} | [{safe}]({fname}) | {ts(ca)} | {ts(ua)} | {count} | {"已删" if da else ""} |')
    # 清孤儿：标题变更会换文件名。按文件头「会话ID」判定——属于本项目、
    # 但文件名不在本次写出集合内的删；其他项目导出的文件不动。
    orphans = []
    for f in os.listdir(arc):
        if not f.endswith('.md') or f in written:
            continue
        try:
            head = open(os.path.join(arc, f), encoding='utf-8').read(256)
        except Exception:
            continue
        m = re.search(r'会话ID: (\S+)', head)
        if m and m.group(1) in sids:
            orphans.append(f)
    for f in orphans:
        os.remove(os.path.join(arc, f))
    if orphans:
        print(f'清理孤儿文件 {len(orphans)} 个: {orphans}')
    idx = ['# Trae 会话存档索引', '', f'> 项目: {path} · 会话 {len(index)} 个（空 {empty} 个未导出）', '',
           '| # | 标题 | 创建 | 更新 | 消息数 | 状态 |', '|---|---|---|---|---|---|'] + index
    open(os.path.join(outdir, '会话索引.md'), 'w').write('\n'.join(idx))
    print(f'导出 {len(index)} 个会话 → {arc}')

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', required=True, help='加密的 database.db 路径')
    ap.add_argument('--project', required=True, help='项目路径子串, 如 my-novel')
    ap.add_argument('--out', required=True, help='输出目录')
    ap.add_argument('--keep-decrypted', action='store_true', help='保留解密库')
    a = ap.parse_args()
    dec = os.path.join(a.out, 'decrypted.db')
    os.makedirs(a.out, exist_ok=True)
    print('解密中…')
    decrypt_db(a.db, dec)
    print('解密完成 →', dec)
    export_sessions(dec, a.project, a.out)
    if not a.keep_decrypted:
        for suffix in ('', '-wal', '-shm'):
            p = dec + suffix
            if os.path.exists(p):
                os.remove(p)
        print('已删除临时解密库（--keep-decrypted 可保留）')
