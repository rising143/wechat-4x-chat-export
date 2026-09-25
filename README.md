# 微信 4.x 聊天记录导出

把 **微信 4.x（Windows）** 的本地聊天记录导出、解密，并转换成 AI 智能体可用的训练语料。

支持输出 **Alpaca / ShareGPT / OpenAI 微调 / RAG 知识库 / 原始归档** 五种格式，可直接用于微调你自己的
对话风格模型，或搭建个人知识库。

---

## 目录

- [它能做什么](#它能做什么)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [输出格式说明](#输出格式说明)
- [目录结构](#目录结构)
- [常见问题](#常见问题)
- [技术原理](#技术原理)
- [隐私与安全](#隐私与安全)
- [许可与致谢](#许可与致谢)

---

## 它能做什么

```
你的微信数据库（加密）
        │
        │  ① 提取密钥
        ▼
   passphrase / raw key
        │
        │  ② 解密（SQLCipher → SQLite）
        ▼
   decrypted/*.db（可直接用 SQLite 工具打开）
        │
        │  ③ 生成语料
        ▼
   alpaca / sharegpt / openai / rag / raw  ← 拿去训练或做知识库
```

另外还附带一个 **聊天风格分析报告**（`wechat-personality/`），用单文件 HTML 展示消息类型分布、
活跃时段、常用词等图表，双击即可在浏览器打开。

---

## 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 / 11 |
| 微信版本 | 4.x（已在 **4.1.11.55** 上测试） |
| Python | 3.10 或更高（仅源码方式需要） |
| 权限 | **管理员权限**（读取微信进程内存以提取密钥） |

Python 依赖安装：

```bash
pip install -r wechat_corpus/requirements.txt
```

---

## 快速开始

> **前提：微信已启动并登录。** 微信是「按需加载」数据库的，建议先在微信里点开几个聊天窗口，
> 否则部分数据库的密钥提取不到。

### 第 1 步：配置数据库目录

复制示例配置并改成你自己的路径：

```bash
cd wechat_corpus/wechat-decrypt
copy config.example.json config.json     # PowerShell 用 cp config.example.json config.json
```

编辑 `config.json`，把 `db_dir` 指向你的微信数据目录：

```json
{
  "db_dir": "C:\\Users\\<你的用户名>\\Documents\\xwechat_files\\<你的wxid>\\db_storage"
}
```

`<你的wxid>` 形如 `wxid_xxxxxxxxxxxx_0b07`，可在上述 `xwechat_files` 目录下直接看到。

### 第 2 步：获取数据库密钥

需要用 **DbkeyHook** 工具从微信进程内存中提取密钥（一串 64 位十六进制字符）。

> ⚠️ **注意**：DbkeyHook 是预编译的 Windows 程序，**不在本仓库中**（本仓库只保留源码）。
> 请从上游 [wechat-decrypt](https://github.com/328336690/wechat-decrypt) 发布包获取，
> 或自行编译。把 `DbkeyHookCMD.exe` 放到 `wechat_corpus/wechat-decrypt/` 目录下。

以**管理员身份**打开 PowerShell：

```powershell
cd wechat_corpus\wechat-decrypt
.\DbkeyHookCMD.exe
```

然后回到微信正常登录，等待输出：

```
获取到DbKey：0a42cad13d0041dc9f0a722c8bffc9bf5071610d499743d6870c5b3008f8e2cc
```

复制这串密钥。也可以直接运行 `run_all.py` 时传入：

```powershell
python wechat_corpus\run_all.py 0a42cad13d0041dc9f0a722c8bffc9bf5071610d499743d6870c5b3008f8e2cc
```

或把它存到 `wechat_corpus/wechat-decrypt/dbkey.txt`（该文件已被 gitignore 排除）。

### 第 3 步：一键解密 + 生成语料

```bash
cd wechat_corpus
python run_all.py
```

脚本会自动检测进度，依次完成 **解密数据库 → 生成语料**，结果输出到 `wechat_corpus/corpus_output/`。

如果想分步执行：

```bash
# 只解密
cd wechat-decrypt && python decrypt_with_passphrase.py

# 只生成语料（可指定格式）
cd .. && python generate_corpus.py --formats alpaca sharegpt
```

---

## 输出格式说明

`generate_corpus.py` 支持 5 种格式，默认全部生成：

| 文件 | 格式 | 用途 | 说明 |
|------|------|------|------|
| `alpaca.jsonl` | Alpaca | LLM 微调 | 对方消息→指令，你的回复→输出。**仅单聊** |
| `sharegpt.jsonl` | ShareGPT | LLM 微调 | 多轮对话，保留完整上下文。**仅单聊** |
| `openai_finetune.jsonl` | OpenAI | OpenAI 微调 API | 带 system prompt 的消息数组 |
| `rag_knowledge.jsonl` | RAG | 向量检索 / 知识库 | 每个会话转为一个知识文档，**含群聊** |
| `conversations_raw.jsonl` | JSONL | 数据归档 / 分析 | 完整原始记录，**含群聊** |
| `statistics.json` | JSON | 统计报告 | 消息量、时间分布、活跃聊天等 |

<details>
<summary>各格式示例（点击展开）</summary>

**Alpaca**

```json
{ "instruction": "周末去看电影吗？", "input": "", "output": "好啊，最近有什么好片？" }
```

**ShareGPT**

```json
{
  "conversations": [
    { "from": "human", "value": "周末去看电影吗？" },
    { "from": "gpt",   "value": "好啊，最近有什么好片？" }
  ]
}
```

**OpenAI**

```json
{
  "messages": [
    { "role": "system",    "content": "你正在模拟与张三的对话风格。" },
    { "role": "user",      "content": "周末去看电影吗？" },
    { "role": "assistant", "content": "好啊，最近有什么好片？" }
  ]
}
```

**RAG**

```json
{
  "id": "chat_wxid_abc123",
  "text": "对话对象: 张三\n对话类型: 单聊\n--- 对话内容 ---\n[2025-01-15 10:30] 张三: 周末去看电影吗？",
  "metadata": { "chat_name": "张三", "chat_type": "单聊", "message_count": 120 }
}
```

</details>

---

## 目录结构

```
.
├── wechat_corpus/                  # 核心：聊天记录 → AI 训练语料
│   ├── wechat-decrypt/             # 密钥提取与数据库解密
│   │   ├── config.example.json     # 配置模板（复制为 config.json 后修改）
│   │   ├── decrypt_with_passphrase.py  # 用 passphrase 解密（run_all.py 调用）
│   │   ├── decrypt_db.py           # 用 all_keys.json 解密
│   │   ├── find_all_keys.py        # 从进程内存扫描密钥
│   │   ├── decode_image.py         # 解密图片（.dat → 图片）
│   │   ├── mcp_server.py           # MCP 服务：把聊天记录暴露给 AI 助手
│   │   └── monitor*.py             # 实时消息监听
│   ├── generate_corpus.py          # 语料生成主脚本
│   ├── run_all.py                  # 一键运行（自动检测进度）
│   └── README.md                   # 更详细的工具说明
│
├── wechat-personality/             # 聊天风格分析报告（单文件 HTML）
│   └── wechat-personality.html
│
└── wechat_export_toolkit/          # 免 Python 环境的分发版说明与批处理脚本
    └── 新电脑操作指南.txt
```

---

## 常见问题

<details>
<summary><b>密钥提取失败？</b></summary>

1. 确认微信已启动并**已登录**
2. 确认以**管理员身份**运行
3. 在微信里多打开几个聊天窗口（微信按需加载数据库，未打开的库没有密钥）
4. 重新运行密钥提取

</details>

<details>
<summary><b>解密后某些数据库缺少密钥？</b></summary>

微信在打开聊天时才加载对应数据库的密钥。多浏览一些聊天记录后重新提取即可。

</details>

<details>
<summary><b>语料里有些消息是空的？</b></summary>

小程序、视频号等消息类型的正文存储在云端，本地数据库里没有文本，属正常现象。

</details>

<details>
<summary><b>怎么区分群聊和单聊？</b></summary>

群聊的 `chat_id` 包含 `@chatroom`，单聊以 `wxid_` 开头。
Alpaca 和 ShareGPT 格式**只含单聊**，RAG 和原始格式包含全部聊天。

</details>

<details>
<summary><b>怎么只生成特定格式？</b></summary>

```bash
python generate_corpus.py --formats alpaca sharegpt
```

可用值：`alpaca` `sharegpt` `openai` `rag` `raw` `stats`

</details>

<details>
<summary><b>怎么指定自定义输出目录或 wxid？</b></summary>

```bash
python generate_corpus.py --output-dir D:\my_corpus --self-wxid wxid_xxx
```

</details>

<details>
<summary><b>怎么查看解密后的数据库？</b></summary>

用 [DB Browser for SQLite](https://sqlitebrowser.org/) 打开 `wechat-decrypt/decrypted/` 下的 `.db` 文件。
主要数据库：`contact/contact.db`（联系人）、`message/message_0.db`~`message_4.db`（聊天记录）、
`session/session.db`（会话列表）、`sns/sns.db`（朋友圈）。

</details>

---

## 技术原理

<details>
<summary><b>微信 4.x 的数据库加密</b></summary>

微信 4.0+ 使用 **SQLCipher 4** 加密本地数据库：

- 加密算法：AES-256-CBC + HMAC-SHA512
- KDF：PBKDF2-HMAC-SHA512，256,000 次迭代
- 页面大小：4096 字节，reserve = 80（IV 16 + HMAC 64）
- 每个数据库有独立的 salt 和 enc_key

</details>

<details>
<summary><b>密钥提取</b></summary>

WCDB（微信对 SQLCipher 的封装）在进程内存中缓存派生后的 raw key，格式为
`x'<64位hex的enc_key><32位hex的salt>'`。工具扫描进程内存中的这种模式，用数据库文件的
salt 去匹配，再通过 HMAC 验证确认密钥正确。

</details>

<details>
<summary><b>消息内容解压</b></summary>

微信 4.x 的 `message_content` 字段对超过约 40 字节的消息使用 **zstd** 压缩
（魔数 `28 B5 2F FD`）。脚本自动检测并解压。

</details>

<details>
<summary><b>发送者识别</b></summary>

通过 `Name2Id` 表的 `rowid` 与消息表的 `real_sender_id` 关联，识别每条消息的发送者，
从而区分「自己发送」和「对方发送」。

</details>

---

## 隐私与安全

**本仓库的 `.gitignore` 强制排除以下内容，请勿移除相关规则：**

| 排除项 | 原因 |
|--------|------|
| `**/decrypted/`、`*.db` | 解密后的数据库含**全部聊天记录原文** |
| `**/corpus_output/`、`*.jsonl` | 生成的语料含个人对话内容 |
| `all_keys.json`、`dbkey*.txt` | 数据库**加密密钥**，泄露等同于数据泄露 |
| `**/config.json` | 含本机 wxid 与绝对路径 |
| `*.exe`、`*.dll` | 预编译二进制，不纳入版本管理 |

**使用注意：**

- 所有数据处理**完全在本地进行**，不上传任何信息
- 解密后的数据库包含全部聊天内容，请妥善保管
- **不要把语料文件或解密数据库上传到任何公开平台**
- 使用完毕后建议删除 `wechat-decrypt/decrypted/` 目录

---

## 许可与致谢

- 数据库解密思路基于 [wechat-decrypt](https://github.com/328336690/wechat-decrypt)（MIT License），
  许可证见 [`wechat_corpus/wechat-decrypt/LICENSE`](wechat_corpus/wechat-decrypt/LICENSE)
- 数据库架构参考 [wechat-to-obsidian](https://github.com/Jane-xiaoer/wechat-to-obsidian)

**仅供个人数据备份与学习研究使用。** 请遵守相关法律法规与微信服务协议，
不要用于侵犯他人隐私或任何非法用途。
