# WeChat Toolkit — 微信聊天记录本地工具箱

本地导出、解密与分析微信 4.x (Windows) 聊天记录的整套工具，用于构建个人 AI 智能体训练语料。

> ⚠️ **隐私声明**：本仓库**只包含代码**。解密后的数据库、聊天语料、数据库密钥均已通过
> `.gitignore` 排除，绝不会被提交。详见下方[隐私与安全](#隐私与安全)。

## 目录结构

```
.
├── wechat_corpus/              # 核心：聊天记录 → AI 训练语料
│   ├── wechat-decrypt/         #   数据库密钥提取与解密工具
│   ├── generate_corpus.py      #   语料生成主脚本
│   ├── run_all.py              #   一键运行（自动检测进度）
│   └── README.md               #   ← 完整使用文档
│
├── wechat-personality/         # 聊天风格分析报告（单文件 HTML + 图表）
│   └── wechat-personality.html
│
└── wechat_export_toolkit/      # 免 Python 环境的分发版（含预编译 exe）
    ├── wechat_export.exe
    └── 新电脑操作指南.txt
```

## 快速开始

完整文档请见 **[wechat_corpus/README.md](wechat_corpus/README.md)**，最简路径：

```bash
# 前提：微信 4.x 已启动并登录，需管理员权限
cd wechat_corpus
python run_all.py
```

该脚本会自动引导完成三步：提取数据库密钥 → 解密数据库 → 生成语料。

若目标机器没有 Python 环境，改用 `wechat_export_toolkit/`，操作步骤见其中的
[新电脑操作指南.txt](wechat_export_toolkit/新电脑操作指南.txt)。

## 输出格式

`generate_corpus.py` 支持 5 种语料格式：

| 文件 | 格式 | 用途 |
|------|------|------|
| `alpaca.jsonl` | Alpaca | LLM 微调（指令-响应对） |
| `sharegpt.jsonl` | ShareGPT | 多轮对话微调 |
| `openai_finetune.jsonl` | OpenAI | OpenAI Fine-tuning API |
| `rag_knowledge.jsonl` | RAG | 向量检索 / 知识库 |
| `conversations_raw.jsonl` | JSONL | 原始对话归档与数据分析 |

## 技术要点

- **加密**：微信 4.0+ 使用 SQLCipher 4（AES-256-CBC + HMAC-SHA512，PBKDF2-HMAC-SHA512 25.6 万次迭代）
- **密钥提取**：扫描微信进程内存中 WCDB 缓存的 raw key，通过 salt 匹配与 HMAC 验证定位正确密钥
- **消息解压**：`message_content` 超过约 40 字节时使用 zstd 压缩，脚本自动识别魔数 `28 B5 2F FD` 并解压
- **发送者识别**：通过 `Name2Id` 表 `rowid` 关联 `real_sender_id`，区分自己与对方发言

## 隐私与安全

本仓库的 `.gitignore` 强制排除以下内容，请勿移除相关规则：

| 排除项 | 原因 |
|--------|------|
| `**/decrypted/`、`*.db` | 解密后的数据库含**全部聊天记录原文** |
| `**/corpus_output/`、`*.jsonl` | 生成的语料含个人对话内容 |
| `all_keys.json`、`dbkey*.txt` | 数据库**加密密钥**，泄露等同于数据泄露 |
| `**/config.json` | 含本机 wxid 与绝对路径 |

- 所有数据处理**完全在本地进行**，不上传任何信息
- 使用完毕后建议删除 `wechat-decrypt/decrypted/` 目录

## 许可与致谢

- 数据库解密工具基于 [wechat-decrypt](https://github.com/328336690/wechat-decrypt)（MIT License），
  其许可证见 [wechat_corpus/wechat-decrypt/LICENSE](wechat_corpus/wechat-decrypt/LICENSE)
- 数据库架构参考 [wechat-to-obsidian](https://github.com/Jane-xiaoer/wechat-to-obsidian)

仅供个人数据备份与学习研究使用，请遵守相关法律法规与微信服务协议。
