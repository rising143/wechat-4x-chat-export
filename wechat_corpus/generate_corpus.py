#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信聊天记录 → 智能体语料 转换工具
适用于微信 4.x (Windows) 解密后的数据库

功能：
  1. 从解密后的 SQLite 数据库中提取所有聊天记录
  2. 处理 zstd 压缩的消息内容
  3. 识别消息发送者（自己 vs 对方）
  4. 生成多种格式的智能体语料：
     - Alpaca 格式 (instruction-response)
     - ShareGPT 格式 (多轮对话)
     - OpenAI 微调格式
     - RAG 知识库格式
     - 原始对话记录 (JSONL)
     - 统计报告

用法：
  python generate_corpus.py [--decrypted-dir DIR] [--output-dir DIR] [--self-wxid WXID]
"""

import os
import sys
import json
import sqlite3
import hashlib
import argparse
import time
from datetime import datetime
from collections import defaultdict, Counter
from pathlib import Path

try:
    import zstandard as zstd
    _zstd_dctx = zstd.ZstdDecompressor()
except ImportError:
    print("[ERROR] 缺少 zstandard 库，请运行: pip install zstandard")
    sys.exit(1)

# ============================================================
# 配置
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WECHAT_DECRYPT_DIR = os.path.join(SCRIPT_DIR, "wechat-decrypt")

# 消息类型映射
MSG_TYPE_MAP = {
    1: "文本",
    3: "图片",
    34: "语音",
    42: "名片",
    43: "视频",
    47: "表情",
    48: "位置",
    49: "链接/文件",
    50: "通话",
    10000: "系统",
    10002: "撤回",
}

# 语料生成参数
TURN_GAP_SECONDS = 300        # 5分钟内的连续消息合并为一个回合
CONVERSATION_GAP_SECONDS = 1800  # 30分钟无消息则分割为新对话
MIN_MESSAGES_PER_CONVERSATION = 2   # 少于此数的对话跳过
MAX_TURNS_PER_CONVERSATION = 20     # 每个对话最多保留的回合数
MIN_TEXT_LENGTH = 1                 # 文本消息最短长度


# ============================================================
# 数据库加载
# ============================================================

def find_decrypted_dir(explicit_dir=None):
    """查找解密后的数据库目录"""
    if explicit_dir:
        if os.path.isdir(explicit_dir):
            return explicit_dir
        else:
            print(f"[ERROR] 指定的解密目录不存在: {explicit_dir}")
            sys.exit(1)

    # 尝试 wechat-decrypt/decrypted
    candidate = os.path.join(WECHAT_DECRYPT_DIR, "decrypted")
    if os.path.isdir(candidate):
        return candidate

    print("[ERROR] 未找到解密后的数据库目录")
    print(f"  期望路径: {candidate}")
    print("\n请先完成数据库解密：")
    print("  1. 启动微信并保持运行")
    print("  2. 以管理员身份运行: cd wechat-decrypt && python find_all_keys.py")
    print("  3. 运行: python decrypt_db.py")
    print("  4. 重新运行本脚本")
    sys.exit(1)


def find_db_files(decrypted_dir, subdir, pattern):
    """在解密目录中查找匹配的数据库文件"""
    search_dir = os.path.join(decrypted_dir, subdir)
    if not os.path.isdir(search_dir):
        return []
    result = []
    for f in sorted(os.listdir(search_dir)):
        if f.endswith(".db") and not f.endswith("-wal") and not f.endswith("-shm"):
            if pattern in f:
                result.append(os.path.join(search_dir, f))
    return result


# ============================================================
# 联系人提取
# ============================================================

def load_contacts(decrypted_dir):
    """从 contact.db 加载联系人信息"""
    contact_db = os.path.join(decrypted_dir, "contact", "contact.db")
    if not os.path.exists(contact_db):
        print("[WARN] 未找到 contact.db，联系人信息将不完整")
        return {}, []

    contacts = {}  # username -> {nick_name, remark, display_name}
    contact_list = []

    conn = sqlite3.connect(contact_db)
    conn.text_factory = bytes
    try:
        # 尝试标准表结构
        rows = conn.execute("""
            SELECT username, nick_name, remark
            FROM contact
        """).fetchall()
    except Exception:
        try:
            # 尝试其他可能的表名/列名
            rows = conn.execute("""
                SELECT username, nickname, remark
                FROM contact
            """).fetchall()
        except Exception as e:
            print(f"[WARN] 无法读取联系人: {e}")
            rows = []
    conn.close()

    for row in rows:
        username = _decode_bytes(row[0])
        nick_name = _decode_bytes(row[1]) if len(row) > 1 else ""
        remark = _decode_bytes(row[2]) if len(row) > 2 else ""
        display = remark if remark else nick_name if nick_name else username
        contacts[username] = {
            "nick_name": nick_name,
            "remark": remark,
            "display_name": display,
        }
        contact_list.append({
            "username": username,
            "nick_name": nick_name,
            "remark": remark,
            "display_name": display,
        })

    print(f"[OK] 加载 {len(contacts)} 个联系人")
    return contacts, contact_list


def _decode_bytes(val):
    """将 bytes 安全解码为字符串"""
    if val is None:
        return ""
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val)


# ============================================================
# 消息提取
# ============================================================

def decompress_content(content, compression_type):
    """解压消息内容"""
    if content is None:
        return None

    # zstd 压缩 (compression_type == 4)
    if compression_type and compression_type == 4 and isinstance(content, bytes):
        try:
            return _zstd_dctx.decompress(content).decode("utf-8", errors="replace")
        except Exception:
            # 尝试流式解压
            try:
                reader = _zstd_dctx.stream_reader(content)
                return reader.read().decode("utf-8", errors="replace")
            except Exception:
                return None

    if isinstance(content, bytes):
        try:
            return content.decode("utf-8", errors="replace")
        except Exception:
            return None

    if isinstance(content, str):
        return content

    return None


def parse_message_content(content, local_type, is_group, self_wxid):
    """解析消息内容，返回 (sender_wxid, text_content)"""
    if content is None:
        return "", ""

    if not isinstance(content, str):
        return "", "(二进制内容)"

    sender = ""
    text = content

    # 群聊消息格式: sender_wxid:\nmessage_text
    if is_group and ":\n" in content:
        parts = content.split(":\n", 1)
        sender = parts[0]
        text = parts[1] if len(parts) > 1 else ""

    # 单聊中，收到的消息可能也有 sender:\n 前缀
    elif not is_group and ":\n" in content:
        parts = content.split(":\n", 1)
        potential_sender = parts[0]
        # 检查是否像 wxid
        if potential_sender.startswith("wxid_") or "@chatroom" in potential_sender:
            sender = potential_sender
            text = parts[1] if len(parts) > 1 else ""

    return sender, text


def extract_messages_from_db(db_path, contacts, self_wxid):
    """从单个消息数据库中提取所有消息"""
    messages = []  # 每条消息: {chat_id, chat_name, sender, sender_name, is_self, timestamp, type, type_name, content}

    conn = sqlite3.connect(db_path)
    conn.text_factory = bytes

    # 加载 Name2Id 映射: rowid -> user_name
    name2id = {}  # rowid -> user_name
    id2name = {}  # user_name -> rowid
    try:
        rows = conn.execute("SELECT rowid, user_name FROM Name2Id").fetchall()
        for rowid, user_name in rows:
            uname = _decode_bytes(user_name)
            name2id[rowid] = uname
            id2name[uname] = rowid
    except Exception:
        pass

    # 查找自己的 rowid（多种匹配策略）
    self_rowids = set()  # 可能有多个 rowid 指向自己
    # 策略1: 精确匹配
    if self_wxid in id2name:
        self_rowids.add(id2name[self_wxid])
    # 策略2: 去掉后缀匹配 (wxid_xxx_0b07 -> wxid_xxx)
    wxid_parts = self_wxid.rsplit("_", 1)
    if len(wxid_parts) == 2 and wxid_parts[0] in id2name:
        self_rowids.add(id2name[wxid_parts[0]])
    # 策略3: 空字符串 user_name 通常是自己的另一个条目
    if "" in id2name:
        self_rowids.add(id2name[""])
    # 策略4: self_wxid 是某个 user_name 的前缀（或反之）
    for uname, rid in id2name.items():
        if uname and (uname in self_wxid or self_wxid in uname):
            self_rowids.add(rid)

    self_rowid = next(iter(self_rowids)) if self_rowids else None

    # 获取所有消息表
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
        ).fetchall()
    except Exception:
        conn.close()
        return messages

    # 构建 hash -> username 的反查映射
    hash_to_username = {}
    for uname in name2id.values():
        h = hashlib.md5(uname.encode("utf-8")).hexdigest()
        hash_to_username[f"Msg_{h}"] = uname

    for (table_name_bytes,) in tables:
        table_name = _decode_bytes(table_name_bytes)
        chat_id = hash_to_username.get(table_name, table_name)

        # 判断是否群聊
        is_group = "@chatroom" in chat_id if chat_id != table_name else False

        # 获取聊天名称
        if chat_id in contacts:
            chat_name = contacts[chat_id]["display_name"]
        else:
            chat_name = chat_id

        # 检查表结构 (text_factory=bytes 导致 PRAGMA 列名也是 bytes，需解码)
        try:
            columns = [_decode_bytes(col[1]) for col in conn.execute(f"PRAGMA table_info([{table_name}])").fetchall()]
        except Exception:
            continue

        # 构建 SQL 查询
        select_cols = ["local_id", "local_type", "create_time"]
        cast_content = False

        if "real_sender_id" in columns:
            select_cols.append("real_sender_id")
        else:
            select_cols.append("NULL as real_sender_id")

        if "message_content" in columns:
            select_cols.append("CAST(message_content AS BLOB) as message_content")
            cast_content = True
        else:
            select_cols.append("NULL as message_content")

        if "WCDB_CT_message_content" in columns:
            select_cols.append("WCDB_CT_message_content")
        else:
            select_cols.append("NULL as WCDB_CT_message_content")

        if "sort_seq" in columns:
            select_cols.append("sort_seq")
        else:
            select_cols.append("NULL as sort_seq")

        sql = f"SELECT {', '.join(select_cols)} FROM [{table_name}] ORDER BY create_time ASC"

        try:
            rows = conn.execute(sql).fetchall()
        except Exception as e:
            print(f"  [WARN] 读取 {table_name} 失败: {e}")
            continue

        for row in rows:
            local_id = row[0]
            local_type = row[1]
            create_time = row[2]
            real_sender_id = row[3]
            raw_content = row[4]
            ct = row[5]
            sort_seq = row[6]

            if create_time is None or create_time <= 0:
                continue

            # 解压消息内容
            content = decompress_content(raw_content, _decode_bytes(ct) if ct else None)

            # 确定发送者
            sender_wxid = ""
            is_self = False

            # 方法1: 通过 real_sender_id（使用 self_rowids 集合匹配）
            if real_sender_id is not None and real_sender_id in name2id:
                sender_wxid = name2id[real_sender_id]
                is_self = (sender_wxid == self_wxid) or (real_sender_id in self_rowids)
            elif real_sender_id is not None and real_sender_id in self_rowids:
                is_self = True
                sender_wxid = self_wxid

            # 方法2: 通过消息内容解析
            parsed_sender, text = parse_message_content(content, local_type, is_group, self_wxid)

            if parsed_sender and not sender_wxid:
                sender_wxid = parsed_sender
                is_self = (sender_wxid == self_wxid)

            if not sender_wxid:
                if is_group:
                    # 群聊中无法确定发送者的消息，默认为对方
                    is_self = False
                else:
                    # 单聊中，real_sender_id 为 NULL/0 通常表示对方发送的消息
                    # 自己发送的消息 real_sender_id 会匹配 self_rowids
                    if real_sender_id is not None and real_sender_id == 0:
                        is_self = False  # 0 = 对方
                    else:
                        # 无法确定时，用消息内容特征判断
                        is_self = False


            # 获取发送者显示名称
            if is_self:
                sender_name = "我"
            elif sender_wxid and sender_wxid in contacts:
                sender_name = contacts[sender_wxid]["display_name"]
            elif sender_wxid:
                sender_name = sender_wxid
            else:
                sender_name = "未知"

            # 处理消息类型
            type_name = MSG_TYPE_MAP.get(local_type, f"type_{local_type}")

            # 对于非文本消息，生成描述性内容
            if local_type != 1 and content:
                if local_type == 3:
                    text = "[图片]"
                elif local_type == 34:
                    text = "[语音]"
                elif local_type == 43:
                    text = "[视频]"
                elif local_type == 47:
                    text = "[表情]"
                elif local_type == 49:
                    # 尝试从 XML 中提取标题
                    text = _extract_link_title(content) or "[链接/文件]"
                elif local_type == 48:
                    text = "[位置]"
                elif local_type == 10000:
                    text = content[:200] if content else "[系统消息]"
                elif local_type == 10002:
                    text = "[撤回消息]"

            if not text and content:
                text = content[:500]

            messages.append({
                "chat_id": chat_id,
                "chat_name": chat_name,
                "is_group": is_group,
                "sender_wxid": sender_wxid,
                "sender_name": sender_name,
                "is_self": is_self,
                "timestamp": create_time,
                "datetime": datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M:%S"),
                "local_type": local_type,
                "type_name": type_name,
                "content": text or "",
            })

    conn.close()
    return messages


def _extract_link_title(content):
    """从链接消息的 XML 内容中提取标题"""
    if not content or not isinstance(content, str):
        return None
    try:
        import re
        match = re.search(r"<title>(.*?)</title>", content, re.DOTALL)
        if match:
            return f"[链接] {match.group(1).strip()}"
        match = re.search(r'<title="([^"]*)"', content)
        if match:
            return f"[链接] {match.group(1)}"
    except Exception:
        pass
    return None


def extract_all_messages(decrypted_dir, contacts, self_wxid):
    """从所有消息数据库中提取消息"""
    all_messages = []

    # 查找所有 message_*.db 文件（排除 fts, resource, biz, media）
    msg_dbs = find_db_files(decrypted_dir, "message", "message_")
    msg_dbs = [db for db in msg_dbs
               if "fts" not in os.path.basename(db)
               and "resource" not in os.path.basename(db)
               and "biz" not in os.path.basename(db)]

    if not msg_dbs:
        print("[ERROR] 未找到消息数据库文件 (message_*.db)")
        print(f"  搜索目录: {os.path.join(decrypted_dir, 'message')}")
        sys.exit(1)

    print(f"\n找到 {len(msg_dbs)} 个消息数据库:")
    for db in msg_dbs:
        size_mb = os.path.getsize(db) / 1024 / 1024
        print(f"  {os.path.basename(db)} ({size_mb:.1f} MB)")

    print()
    for db_path in msg_dbs:
        db_name = os.path.basename(db_path)
        print(f"  正在提取 {db_name} ...", end=" ", flush=True)
        t0 = time.time()
        msgs = extract_messages_from_db(db_path, contacts, self_wxid)
        elapsed = time.time() - t0
        print(f"{len(msgs)} 条消息 ({elapsed:.1f}s)")
        all_messages.extend(msgs)

    print(f"\n[OK] 共提取 {len(all_messages)} 条消息")
    return all_messages


# ============================================================
# 消息分组与对话构建
# ============================================================

def group_messages_by_chat(messages):
    """按聊天分组消息"""
    chats = defaultdict(list)
    for msg in messages:
        chats[msg["chat_id"]].append(msg)

    # 每个聊天内按时间排序
    for chat_id in chats:
        chats[chat_id].sort(key=lambda m: m["timestamp"])

    return dict(chats)


def build_turns(messages, gap_seconds=TURN_GAP_SECONDS):
    """将消息列表按时间间隔分组为回合"""
    if not messages:
        return []

    turns = []
    current_turn = {
        "sender_wxid": messages[0]["sender_wxid"],
        "sender_name": messages[0]["sender_name"],
        "is_self": messages[0]["is_self"],
        "messages": [messages[0]],
        "start_time": messages[0]["timestamp"],
        "end_time": messages[0]["timestamp"],
    }

    for msg in messages[1:]:
        # 时间间隔超过阈值，或发送者变化，开始新回合
        if (msg["timestamp"] - current_turn["end_time"] > gap_seconds
                or msg["is_self"] != current_turn["is_self"]):
            current_turn["text"] = "\n".join(
                m["content"] for m in current_turn["messages"] if m["content"]
            )
            turns.append(current_turn)
            current_turn = {
                "sender_wxid": msg["sender_wxid"],
                "sender_name": msg["sender_name"],
                "is_self": msg["is_self"],
                "messages": [msg],
                "start_time": msg["timestamp"],
                "end_time": msg["timestamp"],
            }
        else:
            current_turn["messages"].append(msg)
            current_turn["end_time"] = msg["timestamp"]

    current_turn["text"] = "\n".join(
        m["content"] for m in current_turn["messages"] if m["content"]
    )
    turns.append(current_turn)

    return turns


def split_conversations(turns, gap_seconds=CONVERSATION_GAP_SECONDS):
    """将回合列表按时间间隔分割为独立对话"""
    if not turns:
        return []

    conversations = []
    current_conv = [turns[0]]

    for turn in turns[1:]:
        if turn["start_time"] - current_conv[-1]["end_time"] > gap_seconds:
            conversations.append(current_conv)
            current_conv = [turn]
        else:
            current_conv.append(turn)

    conversations.append(current_conv)
    return conversations


# ============================================================
# 语料生成
# ============================================================

def generate_alpaca(chats, self_wxid, output_dir):
    """生成 Alpaca 格式语料 (instruction-response)"""
    output_file = os.path.join(output_dir, "alpaca.jsonl")
    count = 0

    with open(output_file, "w", encoding="utf-8") as f:
        for chat_id, messages in chats.items():
            # 只保留文本消息
            text_msgs = [m for m in messages if m["local_type"] == 1 and len(m["content"]) >= MIN_TEXT_LENGTH]
            if len(text_msgs) < MIN_MESSAGES_PER_CONVERSATION:
                continue

            turns = build_turns(text_msgs)
            conversations = split_conversations(turns)

            for conv in conversations:
                if len(conv) < 2:
                    continue

                # 构建 instruction-response 对
                for i in range(len(conv) - 1):
                    inst_turn = conv[i]
                    resp_turn = conv[i + 1]

                    # instruction 来自对方，response 来自自己
                    if not inst_turn["is_self"] and resp_turn["is_self"]:
                        instruction = inst_turn["text"].strip()
                        output = resp_turn["text"].strip()

                        if len(instruction) >= MIN_TEXT_LENGTH and len(output) >= MIN_TEXT_LENGTH:
                            entry = {
                                "instruction": instruction[:2000],
                                "input": "",
                                "output": output[:2000],
                                "history": [],
                            }
                            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                            count += 1

    print(f"  [OK] Alpaca 格式: {count} 条 (alpaca.jsonl)")
    return count


def generate_sharegpt(chats, self_wxid, output_dir):
    """生成 ShareGPT 格式语料 (多轮对话)"""
    output_file = os.path.join(output_dir, "sharegpt.jsonl")
    count = 0

    with open(output_file, "w", encoding="utf-8") as f:
        for chat_id, messages in chats.items():
            text_msgs = [m for m in messages if m["local_type"] == 1 and len(m["content"]) >= MIN_TEXT_LENGTH]
            if len(text_msgs) < MIN_MESSAGES_PER_CONVERSATION:
                continue

            turns = build_turns(text_msgs)
            conversations = split_conversations(turns)

            for conv in conversations:
                if len(conv) < 2:
                    continue
                if len(conv) > MAX_TURNS_PER_CONVERSATION:
                    conv = conv[:MAX_TURNS_PER_CONVERSATION]

                conversations_list = []
                for turn in conv:
                    role = "gpt" if turn["is_self"] else "human"
                    text = turn["text"].strip()
                    if text and len(text) >= MIN_TEXT_LENGTH:
                        conversations_list.append({
                            "from": role,
                            "value": text[:4000],
                        })

                if len(conversations_list) >= 2:
                    entry = {
                        "conversations": conversations_list,
                        "id": f"chat_{chat_id}_{count}",
                    }
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    count += 1

    print(f"  [OK] ShareGPT 格式: {count} 条 (sharegpt.jsonl)")
    return count


def generate_openai_finetune(chats, self_wxid, output_dir):
    """生成 OpenAI 微调格式语料"""
    output_file = os.path.join(output_dir, "openai_finetune.jsonl")
    count = 0

    with open(output_file, "w", encoding="utf-8") as f:
        for chat_id, messages in chats.items():
            text_msgs = [m for m in messages if m["local_type"] == 1 and len(m["content"]) >= MIN_TEXT_LENGTH]
            if len(text_msgs) < MIN_MESSAGES_PER_CONVERSATION:
                continue

            turns = build_turns(text_msgs)
            conversations = split_conversations(turns)

            chat_name = messages[0]["chat_name"] if messages else chat_id

            for conv in conversations:
                if len(conv) < 2:
                    continue
                if len(conv) > MAX_TURNS_PER_CONVERSATION:
                    conv = conv[:MAX_TURNS_PER_CONVERSATION]

                msg_list = [{
                    "role": "system",
                    "content": f"你正在模拟与{chat_name}的对话风格。请根据上下文自然回复。"
                }]

                valid = True
                for turn in conv:
                    role = "assistant" if turn["is_self"] else "user"
                    text = turn["text"].strip()
                    if not text or len(text) < MIN_TEXT_LENGTH:
                        continue
                    msg_list.append({
                        "role": role,
                        "content": text[:4000],
                    })

                if len(msg_list) >= 3:  # system + at least 2 messages
                    entry = {"messages": msg_list}
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    count += 1

    print(f"  [OK] OpenAI 微调格式: {count} 条 (openai_finetune.jsonl)")
    return count


def generate_rag_knowledge(chats, output_dir):
    """生成 RAG 知识库格式语料"""
    output_file = os.path.join(output_dir, "rag_knowledge.jsonl")
    count = 0

    with open(output_file, "w", encoding="utf-8") as f:
        for chat_id, messages in chats.items():
            if len(messages) < 2:
                continue

            chat_name = messages[0]["chat_name"]
            is_group = messages[0]["is_group"]
            chat_type = "群聊" if is_group else "单聊"

            # 构建知识文档
            lines = []
            lines.append(f"对话对象: {chat_name}")
            lines.append(f"对话类型: {chat_type}")
            lines.append(f"消息数量: {len(messages)}")

            if messages:
                time_range = f"{messages[0]['datetime']} ~ {messages[-1]['datetime']}"
                lines.append(f"时间范围: {time_range}")

            lines.append("")
            lines.append("--- 对话内容 ---")

            for msg in messages:
                time_str = msg["datetime"]
                sender = msg["sender_name"]
                content = msg["content"]
                if content:
                    lines.append(f"[{time_str}] {sender}: {content}")

            text = "\n".join(lines)

            entry = {
                "id": f"chat_{chat_id}",
                "text": text[:50000],  # 限制长度
                "metadata": {
                    "chat_id": chat_id,
                    "chat_name": chat_name,
                    "chat_type": chat_type,
                    "message_count": len(messages),
                    "time_start": messages[0]["datetime"] if messages else "",
                    "time_end": messages[-1]["datetime"] if messages else "",
                }
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            count += 1

    print(f"  [OK] RAG 知识库格式: {count} 条 (rag_knowledge.jsonl)")
    return count


def generate_raw_conversations(chats, output_dir):
    """生成原始对话记录 (JSONL)"""
    output_file = os.path.join(output_dir, "conversations_raw.jsonl")
    count = 0

    with open(output_file, "w", encoding="utf-8") as f:
        for chat_id, messages in chats.items():
            if len(messages) < 1:
                continue

            chat_name = messages[0]["chat_name"]
            is_group = messages[0]["is_group"]

            entry = {
                "chat_id": chat_id,
                "chat_name": chat_name,
                "chat_type": "群聊" if is_group else "单聊",
                "message_count": len(messages),
                "time_start": messages[0]["datetime"] if messages else "",
                "time_end": messages[-1]["datetime"] if messages else "",
                "messages": [
                    {
                        "timestamp": m["timestamp"],
                        "datetime": m["datetime"],
                        "sender": m["sender_name"],
                        "sender_wxid": m["sender_wxid"],
                        "is_self": m["is_self"],
                        "type": m["type_name"],
                        "content": m["content"],
                    }
                    for m in messages
                ],
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            count += 1

    print(f"  [OK] 原始对话记录: {count} 个会话 (conversations_raw.jsonl)")
    return count


def generate_statistics(all_messages, chats, contacts, output_dir, counts):
    """生成统计报告"""
    output_file = os.path.join(output_dir, "statistics.json")

    # 基本统计
    total_messages = len(all_messages)
    total_chats = len(chats)
    total_contacts = len(contacts)

    # 群聊 vs 单聊
    group_chats = sum(1 for msgs in chats.values() if msgs and msgs[0]["is_group"])
    private_chats = total_chats - group_chats

    # 消息类型分布
    type_dist = Counter(m["type_name"] for m in all_messages)

    # 发送者统计
    self_messages = sum(1 for m in all_messages if m["is_self"])
    other_messages = total_messages - self_messages

    # 时间范围
    if all_messages:
        timestamps = [m["timestamp"] for m in all_messages if m["timestamp"] > 0]
        if timestamps:
            time_start = datetime.fromtimestamp(min(timestamps)).strftime("%Y-%m-%d %H:%M:%S")
            time_end = datetime.fromtimestamp(max(timestamps)).strftime("%Y-%m-%d %H:%M:%S")
            # 按月统计
            monthly = Counter()
            for m in all_messages:
                if m["timestamp"] > 0:
                    dt = datetime.fromtimestamp(m["timestamp"])
                    monthly[dt.strftime("%Y-%m")] += 1
        else:
            time_start = "未知"
            time_end = "未知"
            monthly = {}
    else:
        time_start = "未知"
        time_end = "未知"
        monthly = {}

    # 活跃聊天 Top 20
    chat_msg_counts = [(chat_id, msgs[0]["chat_name"] if msgs else chat_id, len(msgs))
                       for chat_id, msgs in chats.items()]
    chat_msg_counts.sort(key=lambda x: x[2], reverse=True)
    top_chats = [
        {"chat_name": name, "message_count": count, "is_group": "@chatroom" in cid}
        for cid, name, count in chat_msg_counts[:20]
    ]

    stats = {
        "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "总消息数": total_messages,
        "总会话数": total_chats,
        "群聊数": group_chats,
        "单聊数": private_chats,
        "联系人数": total_contacts,
        "自己发送的消息": self_messages,
        "接收的消息": other_messages,
        "时间范围": {
            "最早": time_start,
            "最晚": time_end,
        },
        "消息类型分布": dict(type_dist.most_common()),
        "月度消息量": dict(sorted(monthly.items())),
        "活跃聊天 Top 20": top_chats,
        "语料文件统计": {
            "alpaca.jsonl": f"{counts.get('alpaca', 0)} 条指令-响应对",
            "sharegpt.jsonl": f"{counts.get('sharegpt', 0)} 条多轮对话",
            "openai_finetune.jsonl": f"{counts.get('openai', 0)} 条微调样本",
            "rag_knowledge.jsonl": f"{counts.get('rag', 0)} 个知识文档",
            "conversations_raw.jsonl": f"{counts.get('raw', 0)} 个原始会话",
        },
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"  [OK] 统计报告 (statistics.json)")
    return stats


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="微信聊天记录 → 智能体语料转换工具")
    parser.add_argument("--decrypted-dir", default=None,
                        help="解密后的数据库目录 (默认: wechat-decrypt/decrypted)")
    parser.add_argument("--output-dir", default=None,
                        help="语料输出目录 (默认: corpus_output)")
    parser.add_argument("--self-wxid", default=None,
                        help="自己的微信 wxid (默认: 自动检测)")
    parser.add_argument("--formats", nargs="+",
                        default=["alpaca", "sharegpt", "openai", "rag", "raw", "stats"],
                        choices=["alpaca", "sharegpt", "openai", "rag", "raw", "stats", "all"],
                        help="要生成的语料格式")
    args = parser.parse_args()

    print("=" * 60)
    print("  微信聊天记录 → 智能体语料 转换工具")
    print("=" * 60)

    # 查找解密目录
    decrypted_dir = find_decrypted_dir(args.decrypted_dir)
    print(f"\n解密数据库目录: {decrypted_dir}")

    # 输出目录
    output_dir = args.output_dir or os.path.join(SCRIPT_DIR, "corpus_output")
    os.makedirs(output_dir, exist_ok=True)
    print(f"语料输出目录: {output_dir}")

    # 自动检测 wxid
    self_wxid = args.self_wxid
    if not self_wxid:
        # 从 db_dir 路径推断
        db_dir = os.path.join(WECHAT_DECRYPT_DIR, "config.json")
        if os.path.exists(db_dir):
            with open(db_dir) as f:
                cfg = json.load(f)
            db_path = cfg.get("db_dir", "")
            # 路径格式: C:\...\xwechat_files\<wxid>\db_storage
            parts = db_path.replace("\\", "/").split("/")
            for part in parts:
                if part.startswith("wxid_"):
                    self_wxid = part
                    break

    if not self_wxid:
        print("[ERROR] 无法自动检测 wxid，请使用 --self-wxid 参数指定")
        sys.exit(1)

    print(f"当前用户 wxid: {self_wxid}")

    # 加载联系人
    print("\n--- 加载联系人 ---")
    contacts, contact_list = load_contacts(decrypted_dir)

    # 提取所有消息
    print("\n--- 提取聊天记录 ---")
    all_messages = extract_all_messages(decrypted_dir, contacts, self_wxid)

    # 按聊天分组
    print("\n--- 分组消息 ---")
    chats = group_messages_by_chat(all_messages)
    print(f"[OK] 共 {len(chats)} 个会话")

    # 生成语料
    print("\n--- 生成语料 ---")
    counts = {}

    formats = args.formats
    if "all" in formats:
        formats = ["alpaca", "sharegpt", "openai", "rag", "raw", "stats"]

    if "alpaca" in formats:
        counts["alpaca"] = generate_alpaca(chats, self_wxid, output_dir)
    if "sharegpt" in formats:
        counts["sharegpt"] = generate_sharegpt(chats, self_wxid, output_dir)
    if "openai" in formats:
        counts["openai"] = generate_openai_finetune(chats, self_wxid, output_dir)
    if "rag" in formats:
        counts["rag"] = generate_rag_knowledge(chats, output_dir)
    if "raw" in formats:
        counts["raw"] = generate_raw_conversations(chats, output_dir)
    if "stats" in formats:
        stats = generate_statistics(all_messages, chats, contacts, output_dir, counts)

    # 完成
    print("\n" + "=" * 60)
    print("  语料生成完成！")
    print("=" * 60)
    print(f"\n输出目录: {output_dir}")
    print(f"\n文件列表:")
    for f in sorted(os.listdir(output_dir)):
        fpath = os.path.join(output_dir, f)
        size = os.path.getsize(fpath)
        size_str = f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/1024/1024:.1f} MB"
        print(f"  {f} ({size_str})")

    # 打印关键统计
    print(f"\n关键统计:")
    print(f"  总消息数: {len(all_messages)}")
    print(f"  总会话数: {len(chats)}")
    if "stats" in formats:
        print(f"  Alpaca 指令对: {counts.get('alpaca', 0)}")
        print(f"  ShareGPT 对话: {counts.get('sharegpt', 0)}")
        print(f"  OpenAI 样本: {counts.get('openai', 0)}")
        print(f"  RAG 文档: {counts.get('rag', 0)}")


if __name__ == "__main__":
    main()
