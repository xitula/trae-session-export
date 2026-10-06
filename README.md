[English](README.en-US.md) | **中文**

# trae-session-export

从本地加密的 `database.db` 中解密并导出**你自己的** Trae CN 对话历史，再对导出的会话存档做分析。

Trae CN 把完整对话（含助手回复）存在一个 SQLCipher 加密的 SQLite 库里。其加密密钥是一个**确定性值**（并非每台机器随机），因此整个库可以用标准 AES-CBC 逐页解密——不需要 `sqlcipher` CLI、不需要 root，除了读取你自己的文件之外没有任何越界操作。

> ⚠️ **适用范围**：仅用于解密**你自己账号、你自己机器上**的数据。本仓库只提供工具与文档——不含任何用户数据。

## 功能特性

- 🔓 **一键解密导出** — `decrypt_export.py` 数秒内重建整库（AES-NI），再按项目把会话导出为 Markdown 存档
- 📊 **会话存档分析** — `analyze_sessions.py` 提供命中数排名、单会话结构统计（轮次 / 工具调用块 / 工具频次）、按体量粗筛数百个存档
- 🔑 **密钥恢复兜底** — 若未来 Trae 版本更换密钥，`brute.c` 用已知明文攻击从进程内存重新导出密钥（方法论致谢：[forum.trae.cn/t/topic/18248](https://forum.trae.cn/t/topic/18248)，已做 macOS 适配）
- 🧰 无常驻服务、纯 CLI；仅一个第三方依赖（`pycryptodome`）

## 环境要求

- macOS（页布局与密钥恢复步骤在 macOS 实测；AES-CBC 逐页解密本身与操作系统无关）
- 带 `pycryptodome` 的 Python 3：

```bash
python3 -m pip install --user --break-system-packages pycryptodome
```

## 快速开始

### 1. 取得 `database.db`

从应用数据目录实时复制：

```
~/Library/Application Support/Trae CN/ModularData/ai-agent/database.db
```

或从官方「导出用户数据」包中取 `trae_<用户名>/user_builder_data/database.db`。

> ⚠️ 实时复制会漏掉 WAL 尾部（尚未 checkpoint 的最近写入）。**复制前重启一次 Trae**，即可拿到合并后的完整库。

### 2. 解密并导出

```bash
python3 decrypt_export.py \
    --db "$HOME/Library/Application Support/Trae CN/ModularData/ai-agent/database.db" \
    --project <你的项目路径子串> \
    --out ./output
```

输出：`会话索引.md`（会话索引）＋ `会话存档/NNN_<标题>.md`（每个会话一份存档：🧑 用户 / 🤖 助手逐条 ＋ 工具调用标注）。`--project` 按项目路径的任意子串过滤；每个项目各跑一次。加 `--keep-decrypted` 可保留重建出的 `decrypted.db` 以便直接跑 SQL 查询。

### 3. 分析存档

```bash
python3 analyze_sessions.py index "<正则1>" ["<正则2>" ...] --top 30  # 跨存档命中排名 → 定位哪些会话相关
python3 analyze_sessions.py stats <存档名> [...]                     # 轮次 / 工具块 / 工具频次 / 用户轮起始行号
python3 analyze_sessions.py top --min-kb 100                          # 按体量粗筛大会话
```

`stats` 会打印每个用户轮的起始行号——之后深读某个会话时，正好用作分窗读取（`Read offset/limit`）的锚点。脚本相对自身定位 `../解析输出/会话存档/`；用 `--dir` 指向别处。

## 工作原理

| 区域 | 位置 | 内容 |
|---|---|---|
| salt | 页1 `[0:16]` | KDF 盐（逐页解密用不到它） |
| 密文 | 每页 `[0:4016]`（页1 为 `[16:4016]`） | AES-256-CBC，每页独立加密，IV 在页尾 |
| IV | 每页 `[4016:4032]` | reserve=80 → iv(16) + HMAC-SHA512(64) |
| HMAC | 每页 `[4032:4096]` | 完整性校验标签——解密时忽略 |

页 1 解密后前 16 字节替换为 `SQLite format 3\0`，即得到标准 SQLite 文件。核心表：`history_v2`（完整消息，JSON）、`chat_session`（会话列表；其 `project_id` 是 `project.absolute_path` 派生的**字符串** id，不是整数 rowid）、`project`、`session_project`。

## 为什么不能用 `sqlcipher` CLI

`PRAGMA key = "x'<密钥>'"` 直接报 `file is not a database`：Trae 的 SQLCipher 用了自定义 HMAC/KDF 参数（未探明），CLI 默认参数过不了完整性校验。`cipher_use_hmac=OFF`、`cipher_compatibility=3`、各种 `kdf_iter`——全是死路。**结论：放弃 sqlcipher，直接用 Python AES-CBC 逐页解密。**

## 密钥参考

```
3605f6691095a993f03d5009c918352ef5be31ae31e8f000212b81ff058da773
```

AES-256 原始密钥，由 Trae CN 确定性生成（论坛公开逆向成果报同一值 → 非每机随机、非任何人的个人秘密）。2026-09-29 与 2026-10-07 两次导出实测**仍有效**。若未来版本更换，见下。

<details>
<summary><b>从内存恢复密钥（仅当内置密钥失效时）</b></summary>

方法论 = 上面那篇论坛帖 ＋ macOS 适配，全程约 10 分钟：

1. **克隆数据目录**（APFS clonefile，秒级）：`cp -Rc "~/Library/Application Support/Trae CN" /tmp/trae_copy`
2. **克隆应用并 ad-hoc 重签**（绕开 AMFI 硬化运行时）：`cp -Rc "/Applications/Trae CN.app" /tmp/app_copy`，再对每个 Mach-O `codesign -f -s -`（deep）
3. **用 osascript 拉起第二实例**（绕开 Trae 沙箱包装器）：`do shell script "nohup /tmp/app_copy/Contents/MacOS/Electron --user-data-dir=/tmp/trae_copy --no-sandbox --disable-gpu &"`——主实例与当前会话全程不受影响
4. **lldb 附加**持有 db 的子进程（`lsof /tmp/trae_copy/.../database.db` → PID）→ 按区域倒内存（注意：本机 lldb 暴露的是 `GetMemoryRegionAtIndex(i, idx)`，不是 `GetRegionAtIndex`）
5. **已知明文扫密钥**：编译 `brute.c`（`cc -O2`）；它对每个 4 字节对齐的 32 字节窗口做单块 AES 解密，比对 SQLite 头明文。已知明文：页 1 块 `[16:32]` → `10 00 [01|02] [01|02] 50 40 20 20`。**务必先跑内置自测**（曾因扫描循环起始偏移写错而静默漏扫全部）
6. 命中后用 `decrypt_export.py` 解密导出；清理 `/tmp/app_copy /tmp/trae_copy`

</details>

## 踩过的坑

- 硬化运行时：`task_for_pid` 对普通用户**和** root 一律拒绝（kern=5）；lldb attach 也被拒——只有父调试器拉起或去签名才行
- Trae 沙箱包装器会拦截直接 exec（`.sandbox_exec`、库校验报错）→ 用 `osascript do shell script` 拉起
- 完全剥签名会让 dyld 拒载 `libffmpeg.dylib` → **必须 ad-hoc 重签**
- 官方「导出用户数据」包**不含助手回复**（只有输入历史＋图片）；完整对话只在加密的 `user_builder_data/database.db` 里
- 内存扫描时第二实例会把聊天缓存载入内存——论坛帖文本 / 你自己的对话文本会污染正则候选；命中要甄别
- 新版 Trae 把 `tool_calls.function` 改名为 `function_call`；`decrypt_export.py` 已兼容双格式并带出参数摘要
- 会话标题事后变更 → 按新名重写文件、旧名残留成孤儿；导出现已按「会话 ID 不在本次写出集合」自动清理
- 解密库用 `journal_mode=wal`；只读连接关闭后在输出目录留 `-wal`/`-shm` 兄弟文件；现已一并删除

## 文件结构

```
trae-session-export/
├── README.md            # 中文（本文件）
├── README.en-US.md      # English
├── LICENSE              # MIT
├── decrypt_export.py    # 一键解密 + 按项目导出会话（日常用这个）
├── analyze_sessions.py  # 存档分析：index / stats / top
├── brute.c              # 已知明文内存扫密钥器（编译：cc -O2；内置自测）
└── scan2.py             # 备选内存 hex 模式扫描（兜底方案，最终一轮未直接命中）
```

## 实测记录

| 日期 | 库大小 | 会话数 | 备注 |
|---|---|---|---|
| 2026-09-25 | 303 MB | 首次全流程 | 密钥＋页布局确认 |
| 2026-09-29 | 364 MB | 268（导出 266，2 空） | AES-NI 下解密＋导出 ≈3 秒 |
| 2026-10-07 | 523 MB（127,877 页） | 428（导出 426） | ≈40 秒；三项导出修复落地（见踩坑） |

编号 `1–268` 跨多次导出保持稳定；空会话占号但不产文件（跳号正常）。

## 免责声明

针对第三方应用本地存储的逆向工具，仅为互操作性与个人数据可携带性提供。使用前请确认符合 Trae CN 的服务条款，并严格限于**你自己的**数据。本软件按「现状」提供，不含任何形式的担保。

## 许可

[MIT](LICENSE)
