# 微信聊天记录 → 智能体语料 转换工具

将微信 4.x (Windows) 的全部聊天记录导出为多种格式的 AI 智能体训练语料。

## 适用环境

- Windows 10/11
- 微信 4.x (已测试 4.1.11.55)
- Python 3.10+
- 需要管理员权限（读取微信进程内存提取密钥）

## 快速开始

### 一键运行（推荐）

```bash
# 确保微信已启动并登录，然后运行：
python run_all.py
```

脚本会自动检测进度，引导你完成全部 3 个步骤。

### 分步运行

#### 步骤 1：提取数据库密钥

> 前提：微信已启动并登录

```bash
cd wechat-decrypt
# 以管理员身份运行（右键 → 以管理员身份运行终端）
python find_all_keys.py
```

这会从微信进程内存中提取所有数据库的加密密钥，保存到 `all_keys.json`。

#### 步骤 2：解密数据库

```bash
cd wechat-decrypt
python decrypt_db.py
```

解密后的数据库保存在 `wechat-decrypt/decrypted/` 目录，可直接用 SQLite 工具打开。

#### 步骤 3：生成智能体语料

```bash
python generate_corpus.py
```

语料文件输出到 `corpus_output/` 目录。

## 输出文件说明

| 文件 | 格式 | 用途 | 说明 |
|------|------|------|------|
| `alpaca.jsonl` | Alpaca | LLM 微调 | 指令-响应对，对方消息→指令，你的回复→输出 |
| `sharegpt.jsonl` | ShareGPT | LLM 微调 | 多轮对话格式，保留完整上下文 |
| `openai_finetune.jsonl` | OpenAI | OpenAI 微调 API | 兼容 OpenAI Fine-tuning 格式 |
| `rag_knowledge.jsonl` | RAG | 向量检索/知识库 | 每个会话转为一个知识文档 |
| `conversations_raw.jsonl` | JSONL | 数据分析/归档 | 完整的原始对话记录 |
| `statistics.json` | JSON | 统计报告 | 消息量、时间分布、活跃聊天等 |

## 语料格式示例

### Alpaca 格式 (alpaca.jsonl)

```json
{
  "instruction": "周末去看电影吗？",
  "input": "",
  "output": "好啊，最近有什么好片？"
}
```

### ShareGPT 格式 (sharegpt.jsonl)

```json
{
  "conversations": [
    {"from": "human", "value": "周末去看电影吗？"},
    {"from": "gpt", "value": "好啊，最近有什么好片？"},
    {"from": "human", "value": "新出的那个科幻片"},
    {"from": "gpt", "value": "行，几点？"}
  ]
}
```

### OpenAI 微调格式 (openai_finetune.jsonl)

```json
{
  "messages": [
    {"role": "system", "content": "你正在模拟与张三的对话风格。"},
    {"role": "user", "content": "周末去看电影吗？"},
    {"role": "assistant", "content": "好啊，最近有什么好片？"}
  ]
}
```

### RAG 知识库格式 (rag_knowledge.jsonl)

```json
{
  "id": "chat_wxid_abc123",
  "text": "对话对象: 张三\n对话类型: 单聊\n--- 对话内容 ---\n[2025-01-15 10:30] 张三: 周末去看电影吗？\n[2025-01-15 10:31] 我: 好啊",
  "metadata": {"chat_name": "张三", "chat_type": "单聊", "message_count": 120}
}
```

## 技术原理

### 微信 4.x 数据库加密

微信 4.0+ 使用 SQLCipher 4 加密本地数据库：

- 加密算法：AES-256-CBC + HMAC-SHA512
- KDF：PBKDF2-HMAC-SHA512，256,000 次迭代
- 页面大小：4096 字节，reserve = 80 (IV 16 + HMAC 64)
- 每个数据库有独立的 salt 和 enc_key

### 密钥提取

WCDB（微信的 SQLCipher 封装）在进程内存中缓存派生后的 raw key，格式为 `x'<64hex_enc_key><32hex_salt>'`。工具通过扫描进程内存中的这种模式，匹配数据库文件的 salt，并通过 HMAC 验证来提取正确的密钥。

### 消息内容处理

微信 4.x 的 `message_content` 字段对超过约 40 字节的消息使用 zstd 压缩（magic `28 B5 2F FD`）。工具自动检测并解压。

### 发送者识别

通过 `Name2Id` 表的 `rowid` 与消息表中的 `real_sender_id` 关联，识别每条消息的发送者，区分"自己发送"和"对方发送"。

## 高级用法

### 只生成特定格式

```bash
python generate_corpus.py --formats alpaca sharegpt
```

### 自定义参数

```bash
python generate_corpus.py --output-dir D:\my_corpus --self-wxid wxid_xxx
```

### 查看解密后的数据库

可以使用 [DB Browser for SQLite](https://sqlitebrowser.org/) 打开 `wechat-decrypt/decrypted/` 下的 `.db` 文件。

主要数据库：
- `contact/contact.db` - 联系人
- `message/message_0.db` ~ `message_4.db` - 聊天记录
- `session/session.db` - 会话列表
- `sns/sns.db` - 朋友圈

## 常见问题

### Q: 提取密钥失败？

1. 确保微信正在运行且已登录
2. 确保以管理员身份运行脚本
3. 尝试在微信中打开几个聊天窗口（微信按需加载数据库）

### Q: 解密后某些数据库缺少密钥？

微信在打开聊天时才加载对应数据库的密钥。尝试在微信中浏览更多聊天记录，然后重新运行密钥提取。

### Q: 语料中有些消息内容为空？

某些消息类型（如小程序、视频号内容）的数据存储在云端，本地数据库中没有文本内容。

### Q: 如何区分群聊和单聊？

群聊的 chat_id 包含 `@chatroom`，单聊则是 `wxid_` 开头。Alpaca 和 ShareGPT 格式仅包含单聊，RAG 和原始格式包含所有聊天。

## 目录结构

```
wechat_corpus/
├── wechat-decrypt/          # 数据库解密工具
│   ├── config.json          # 配置文件（已为你设置好路径）
│   ├── find_all_keys.py     # 密钥提取脚本
│   ├── decrypt_db.py        # 数据库解密脚本
│   ├── decrypted/           # 解密后的数据库（运行后生成）
│   └── all_keys.json        # 提取的密钥（运行后生成）
├── generate_corpus.py       # 语料生成主脚本
├── run_all.py               # 一键运行脚本
├── requirements.txt         # Python 依赖
├── corpus_output/           # 语料输出目录（运行后生成）
│   ├── alpaca.jsonl
│   ├── sharegpt.jsonl
│   ├── openai_finetune.jsonl
│   ├── rag_knowledge.jsonl
│   ├── conversations_raw.jsonl
│   └── statistics.json
└── README.md
```

## 隐私与安全

- 所有数据处理完全在本地进行，不上传任何信息
- 解密后的数据库包含所有聊天内容，请妥善保管
- 语料文件包含个人对话，请勿分享或上传到公开平台
- 使用完毕后建议删除 `decrypted/` 目录

## 致谢

- 数据库解密工具基于 [wechat-decrypt](https://github.com/328336690/wechat-decrypt) (MIT License)
- 数据库架构参考 [wechat-to-obsidian](https://github.com/Jane-xiaoer/wechat-to-obsidian)
