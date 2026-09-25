"""
微信 4.1.x 数据库解密器 (Passphrase 模式)

使用从 DbkeyHookCMD/DbkeyHookUI 提取的 passphrase 密钥，
通过 PBKDF2-HMAC-SHA512 (256,000次迭代) 推导每个数据库的 raw key，
然后解密 SQLCipher 4 加密的数据库。

用法:
  python decrypt_with_passphrase.py <passphrase_hex>
  python decrypt_with_passphrase.py  (从 dbkey.txt 读取)

参数:
  passphrase_hex: 64位十六进制字符串 (32字节)
"""
import hashlib, struct, os, sys, json
import hmac as hmac_mod
from Crypto.Cipher import AES
import functools

print = functools.partial(print, flush=True)

PAGE_SZ = 4096
KEY_SZ = 32
SALT_SZ = 16
IV_SZ = 16
HMAC_SZ = 64
RESERVE_SZ = 80  # IV(16) + HMAC(64)
SQLITE_HDR = b'SQLite format 3\x00'
PBKDF2_ITER = 256000  # 微信4.x使用256,000次迭代

# 加载配置
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(SCRIPT_DIR, "config.json")) as f:
    _cfg = json.load(f)
DB_DIR = _cfg["db_dir"]
OUT_DIR = os.path.join(SCRIPT_DIR, _cfg.get("decrypted_dir", "decrypted"))


def derive_raw_key(passphrase: bytes, salt: bytes) -> bytes:
    """从 passphrase + salt 推导 raw key (PBKDF2-HMAC-SHA512, 256000次)"""
    return hashlib.pbkdf2_hmac('sha512', passphrase, salt, PBKDF2_ITER, dklen=KEY_SZ)


def derive_mac_key(enc_key: bytes, salt: bytes) -> bytes:
    """从 enc_key 派生 HMAC 密钥"""
    mac_salt = bytes(b ^ 0x3a for b in salt)
    return hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=KEY_SZ)


def verify_key(enc_key: bytes, salt: bytes, page1: bytes) -> bool:
    """验证密钥是否正确 (通过 page 1 的 HMAC)"""
    mac_key = derive_mac_key(enc_key, salt)
    hmac_data = page1[SALT_SZ : PAGE_SZ - RESERVE_SZ + IV_SZ]
    stored_hmac = page1[PAGE_SZ - HMAC_SZ : PAGE_SZ]
    hm = hmac_mod.new(mac_key, hmac_data, hashlib.sha512)
    hm.update(struct.pack('<I', 1))  # page number = 1
    return hm.digest() == stored_hmac


def decrypt_page(enc_key: bytes, page_data: bytes, pgno: int) -> bytes:
    """解密单个页面"""
    iv = page_data[PAGE_SZ - RESERVE_SZ : PAGE_SZ - RESERVE_SZ + IV_SZ]

    if pgno == 1:
        encrypted = page_data[SALT_SZ : PAGE_SZ - RESERVE_SZ]
        cipher = AES.new(enc_key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(encrypted)
        page = bytearray(SQLITE_HDR + decrypted + b'\x00' * RESERVE_SZ)
        return bytes(page)
    else:
        encrypted = page_data[:PAGE_SZ - RESERVE_SZ]
        cipher = AES.new(enc_key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(encrypted)
        return decrypted + b'\x00' * RESERVE_SZ


def decrypt_database(db_path: str, out_path: str, enc_key: bytes) -> bool:
    """解密整个数据库文件"""
    file_size = os.path.getsize(db_path)
    total_pages = file_size // PAGE_SZ

    if file_size % PAGE_SZ != 0:
        total_pages += 1

    with open(db_path, 'rb') as fin:
        page1 = fin.read(PAGE_SZ)

    if len(page1) < PAGE_SZ:
        print(f"  [ERROR] 文件太小")
        return False

    # 提取 salt 并验证
    salt = page1[:SALT_SZ]
    if not verify_key(enc_key, salt, page1):
        print(f"  [ERROR] HMAC验证失败!")
        return False

    print(f"  HMAC OK, {total_pages} pages", end="")

    # 解密所有页面
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(db_path, 'rb') as fin, open(out_path, 'wb') as fout:
        for pgno in range(1, total_pages + 1):
            page = fin.read(PAGE_SZ)
            if len(page) < PAGE_SZ:
                if len(page) > 0:
                    page = page + b'\x00' * (PAGE_SZ - len(page))
                else:
                    break

            decrypted = decrypt_page(enc_key, page, pgno)
            fout.write(decrypted)

            if pgno == 1 and decrypted[:16] != SQLITE_HDR:
                print(f"  [WARN] 解密后header不匹配!")

            if pgno % 10000 == 0:
                print(f"  进度: {pgno}/{total_pages} ({100*pgno/total_pages:.1f}%)")

    return True


def main():
    print("=" * 60)
    print("  微信 4.1.x 数据库解密器 (Passphrase 模式)")
    print("=" * 60)

    # 获取 passphrase
    passphrase_hex = None
    if len(sys.argv) > 1:
        passphrase_hex = sys.argv[1].strip()
    else:
        # 从 dbkey.txt 读取
        dbkey_paths = [
            os.path.join(SCRIPT_DIR, "dbkey.txt"),
            os.path.join(SCRIPT_DIR, "..", "dbkey.txt"),
            r"C:\personalsoftware\Weixin\dbkey.txt",
        ]
        for p in dbkey_paths:
            if os.path.exists(p):
                with open(p, 'r') as f:
                    content = f.read().strip()
                # 提取 hex 字符串 (可能包含其他文本)
                import re
                match = re.search(r'([0-9a-fA-F]{64})', content)
                if match:
                    passphrase_hex = match.group(1)
                    print(f"从 {p} 读取到 passphrase")
                    break

    if not passphrase_hex:
        print("\n[ERROR] 未找到 passphrase 密钥")
        print("用法: python decrypt_with_passphrase.py <passphrase_hex>")
        print("  或将密钥保存到 dbkey.txt 文件中")
        print("  或运行 DbkeyHookCMD/DbkeyHookUI 获取密钥")
        sys.exit(1)

    # 验证 passphrase 格式
    passphrase_hex = passphrase_hex.lower().strip()
    if len(passphrase_hex) != 64 or not all(c in '0123456789abcdef' for c in passphrase_hex):
        print(f"[ERROR] passphrase 格式错误: 需64位十六进制字符串, 当前长度={len(passphrase_hex)}")
        sys.exit(1)

    passphrase = bytes.fromhex(passphrase_hex)
    print(f"\nPassphrase: {passphrase_hex}")
    print(f"数据库目录: {DB_DIR}")
    print(f"输出目录: {OUT_DIR}")

    # 收集所有数据库文件
    db_files = []
    for root, dirs, files in os.walk(DB_DIR):
        for f in files:
            if f.endswith('.db') and not f.endswith('-wal') and not f.endswith('-shm'):
                path = os.path.join(root, f)
                rel = os.path.relpath(path, DB_DIR)
                sz = os.path.getsize(path)
                if sz >= PAGE_SZ:
                    db_files.append((rel, path, sz))

    db_files.sort(key=lambda x: x[2])  # 从小到大
    print(f"找到 {len(db_files)} 个数据库文件\n")

    # 解密每个数据库
    success = 0
    failed = 0
    total_bytes = 0
    key_map = {}  # 保存 raw key 信息

    for idx, (rel, path, sz) in enumerate(db_files):
        # 读取 salt
        with open(path, 'rb') as f:
            page1 = f.read(PAGE_SZ)
        salt = page1[:SALT_SZ]
        salt_hex = salt.hex()

        # 推导 raw key
        print(f"[{idx+1}/{len(db_files)}] {rel} ({sz/1024/1024:.1f}MB) ...", end=" ")

        enc_key = derive_raw_key(passphrase, salt)

        out_path = os.path.join(OUT_DIR, rel)
        ok = decrypt_database(path, out_path, enc_key)

        if ok:
            # SQLite 验证
            try:
                import sqlite3
                conn = sqlite3.connect(out_path)
                tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                conn.close()
                table_names = [t[0] for t in tables]
                print(f" OK! 表: {', '.join(table_names[:5])}", end="")
                if len(table_names) > 5:
                    print(f" ...共{len(table_names)}个", end="")
                print()
                success += 1
                total_bytes += sz
                key_map[rel] = {
                    "enc_key": enc_key.hex(),
                    "salt": salt_hex,
                    "size_mb": round(sz / 1024 / 1024, 1)
                }
            except Exception as e:
                print(f"  [WARN] SQLite验证失败: {e}")
                failed += 1
        else:
            failed += 1

    # 保存密钥信息
    keys_file = os.path.join(SCRIPT_DIR, "all_keys.json")
    with open(keys_file, 'w') as f:
        json.dump(key_map, f, indent=2)
    print(f"\n密钥信息已保存到: {keys_file}")

    print(f"\n{'='*60}")
    print(f"结果: {success} 成功, {failed} 失败, 共 {len(db_files)} 个")
    print(f"解密数据量: {total_bytes/1024/1024/1024:.1f}GB")
    print(f"解密文件在: {OUT_DIR}")


if __name__ == '__main__':
    main()
