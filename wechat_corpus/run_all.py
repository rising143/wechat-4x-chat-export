#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信聊天记录 → 智能体语料 一键运行脚本 (Passphrase 模式)

适用于微信 4.1.x，使用 DbkeyHookCMD 提取的 passphrase 密钥

用法:
  python run_all.py <passphrase_hex>        # 使用指定密钥运行
  python run_all.py                         # 从 dbkey.txt 读取密钥
  python run_all.py --step 3                # 只运行步骤3 (语料生成)
"""

import os
import sys
import json
import subprocess
import argparse
import re
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WECHAT_DECRYPT_DIR = os.path.join(SCRIPT_DIR, "wechat-decrypt")
PYTHON_EXE = sys.executable

CONFIG_FILE = os.path.join(WECHAT_DECRYPT_DIR, "config.json")
KEYS_FILE = os.path.join(WECHAT_DECRYPT_DIR, "all_keys.json")
DECRYPTED_DIR = os.path.join(WECHAT_DECRYPT_DIR, "decrypted")
CORPUS_OUTPUT = os.path.join(SCRIPT_DIR, "corpus_output")
DBKEY_FILE = os.path.join(WECHAT_DECRYPT_DIR, "dbkey.txt")


def print_banner():
    print()
    print("=" * 60)
    print("  微信聊天记录 → 智能体语料 一键工具")
    print("  适用于微信 4.1.x (Windows) - Passphrase 模式")
    print("=" * 60)
    print()


def get_passphrase():
    """获取 passphrase 密钥"""
    # 从命令行参数获取
    if len(sys.argv) > 1 and not sys.argv[1].startswith('--'):
        passphrase = sys.argv[1].strip().lower()
        if len(passphrase) == 64 and re.match(r'^[0-9a-f]{64}$', passphrase):
            return passphrase
        else:
            print(f"[ERROR] 密钥格式错误: 需要64位十六进制字符串")
            sys.exit(1)

    # 从 dbkey.txt 读取
    dbkey_paths = [
        DBKEY_FILE,
        os.path.join(WECHAT_DECRYPT_DIR, "dbkey.txt"),
        r"C:\personalsoftware\Weixin\dbkey.txt",
    ]
    for p in dbkey_paths:
        if os.path.exists(p):
            with open(p, 'r') as f:
                content = f.read().strip()
            match = re.search(r'([0-9a-fA-F]{64})', content)
            if match:
                passphrase = match.group(1).lower()
                print(f"从 {p} 读取到 passphrase")
                return passphrase

    # 从 all_keys.json 读取 (如果已有 raw key)
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE) as f:
            keys = json.load(f)
        if keys:
            print(f"已有 {len(keys)} 个数据库密钥 (all_keys.json)")
            return "EXISTING_KEYS"

    print("[ERROR] 未找到 passphrase 密钥")
    print()
    print("请通过以下方式获取密钥:")
    print("  1. 运行 DbkeyHookCMD.exe (以管理员身份)")
    print("  2. 运行 DbkeyHookUI.exe (图形界面)")
    print("  3. 将密钥保存到 dbkey.txt")
    print()
    print("然后运行:")
    print(f"  python run_all.py <passphrase_hex>")
    sys.exit(1)


def step1_decrypt(passphrase):
    """步骤1: 使用 passphrase 解密所有数据库"""
    print("-" * 60)
    print("  步骤 1/2: 解密数据库")
    print("-" * 60)
    print()

    if passphrase == "EXISTING_KEYS":
        print("[OK] 已有密钥，跳过解密")
        # 验证解密文件是否存在
        if os.path.isdir(DECRYPTED_DIR):
            db_count = sum(1 for _, _, files in os.walk(DECRYPTED_DIR) for f in files if f.endswith('.db') and not f.endswith('-wal') and not f.endswith('-shm'))
            if db_count > 0:
                print(f"[OK] 已有 {db_count} 个解密数据库")
                return True

    print(f"Passphrase: {passphrase[:16]}...{passphrase[-16:]}")
    print(f"数据库目录: {json.load(open(CONFIG_FILE))['db_dir']}")
    print(f"输出目录: {DECRYPTED_DIR}")
    print()

    script = os.path.join(WECHAT_DECRYPT_DIR, "decrypt_with_passphrase.py")
    os.chdir(WECHAT_DECRYPT_DIR)
    subprocess.run([PYTHON_EXE, script, passphrase])

    # 验证解密结果
    if not os.path.isdir(DECRYPTED_DIR):
        print("\n[ERROR] 解密目录未生成")
        return False

    db_count = sum(1 for _, _, files in os.walk(DECRYPTED_DIR) for f in files if f.endswith('.db') and not f.endswith('-wal') and not f.endswith('-shm'))
    print(f"\n[OK] 解密完成！共 {db_count} 个数据库文件")
    return True


def step2_generate_corpus():
    """步骤2: 生成智能体语料"""
    print()
    print("-" * 60)
    print("  步骤 2/2: 生成智能体语料")
    print("-" * 60)
    print()

    script = os.path.join(SCRIPT_DIR, "generate_corpus.py")
    subprocess.run([
        PYTHON_EXE, script,
        "--decrypted-dir", DECRYPTED_DIR,
        "--output-dir", CORPUS_OUTPUT,
    ])

    print()
    if os.path.isdir(CORPUS_OUTPUT) and os.listdir(CORPUS_OUTPUT):
        print("[OK] 语料生成完成！")
        return True
    else:
        print("[ERROR] 语料生成可能失败")
        return False


def main():
    parser = argparse.ArgumentParser(description="微信聊天记录 → 智能体语料 一键工具")
    parser.add_argument("passphrase", nargs="?", help="Passphrase 密钥 (64位十六进制)")
    parser.add_argument("--step", type=int, choices=[1, 2], help="只运行指定步骤")
    args = parser.parse_args()

    print_banner()

    # 环境检查
    print("环境检查:")
    print(f"  Python: {PYTHON_EXE}")
    print(f"  工具目录: {WECHAT_DECRYPT_DIR}")

    if not os.path.exists(CONFIG_FILE):
        print("\n[ERROR] 配置文件不存在")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
    print(f"  微信数据: {cfg.get('db_dir', '未配置')}")

    # 检查依赖
    try:
        from Crypto.Cipher import AES
        print(f"  pycryptodome: OK")
    except ImportError:
        print("  [!] 安装 pycryptodome...")
        subprocess.run([PYTHON_EXE, "-m", "pip", "install", "pycryptodome", "--quiet"])

    try:
        import zstandard
        print(f"  zstandard: {zstandard.__version__}")
    except ImportError:
        print("  [!] 安装 zstandard...")
        subprocess.run([PYTHON_EXE, "-m", "pip", "install", "zstandard", "--quiet"])

    # 检查当前进度
    has_decrypted = os.path.isdir(DECRYPTED_DIR) and any(
        f.endswith(".db") for _, _, files in os.walk(DECRYPTED_DIR) for f in files
    )
    has_corpus = os.path.isdir(CORPUS_OUTPUT) and os.listdir(CORPUS_OUTPUT)

    print()
    print("进度检测:")
    print(f"  [{'x' if has_decrypted else ' '}] 步骤1: 数据库已解密")
    print(f"  [{'x' if has_corpus else ' '}] 步骤2: 语料已生成")
    print()

    # 确定从哪一步开始
    if args.step:
        start_step = args.step
    elif not has_decrypted:
        start_step = 1
    elif not has_corpus:
        start_step = 2
    else:
        print("所有步骤已完成！")
        print(f"  语料输出目录: {CORPUS_OUTPUT}")
        choice = input("\n是否重新生成语料？(y/n): ").strip().lower()
        if choice == 'y':
            start_step = 2
        else:
            return

    # 获取 passphrase
    if start_step == 1:
        passphrase = get_passphrase()
    else:
        passphrase = None

    print(f"从步骤 {start_step} 开始")
    print()

    if start_step <= 1:
        if not step1_decrypt(passphrase):
            sys.exit(1)
    if start_step <= 2:
        if not step2_generate_corpus():
            sys.exit(1)

    # 最终输出
    print()
    print("=" * 60)
    print("  全部完成！")
    print("=" * 60)
    print()
    print(f"语料输出目录: {CORPUS_OUTPUT}")
    print()
    print("文件说明:")
    print("  alpaca.jsonl            - Alpaca 指令-响应格式 (用于 LLM 微调)")
    print("  sharegpt.jsonl          - ShareGPT 多轮对话格式 (用于 LLM 微调)")
    print("  openai_finetune.jsonl   - OpenAI 微调 API 格式")
    print("  rag_knowledge.jsonl     - RAG 知识库格式 (用于向量检索)")
    print("  conversations_raw.jsonl - 原始对话记录 (完整数据)")
    print("  statistics.json         - 统计报告")
    print()


if __name__ == "__main__":
    main()
