"""
增强版密钥提取 - 扫描所有微信进程，直接搜索 salt 字节

微信 4.x 懒加载数据库密钥：只有打开聊天时才派生密钥。
本脚本同时搜索:
  1. x'<hex>' 格式的缓存密钥 (WCDB 格式)
  2. 原始 salt 字节 (16字节，直接在内存中匹配数据库文件头)
当找到 salt 时，在附近内存中搜索 32 字节 enc_key 并通过 HMAC 验证。
"""
import ctypes
import ctypes.wintypes as wt
import struct, os, sys, hashlib, time, re, json
import hmac as hmac_mod
from Crypto.Cipher import AES

import functools
print = functools.partial(print, flush=True)

kernel32 = ctypes.windll.kernel32
MEM_COMMIT = 0x1000
READABLE = {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80}
PAGE_SZ = 4096
KEY_SZ = 32
SALT_SZ = 16

# 加载配置
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
with open(CONFIG_FILE) as f:
    _cfg = json.load(f)
DB_DIR = _cfg["db_dir"]
OUT_FILE = os.path.join(SCRIPT_DIR, "all_keys.json")

class MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_uint64), ("AllocationBase", ctypes.c_uint64),
        ("AllocationProtect", wt.DWORD), ("_pad1", wt.DWORD),
        ("RegionSize", ctypes.c_uint64), ("State", wt.DWORD),
        ("Protect", wt.DWORD), ("Type", wt.DWORD), ("_pad2", wt.DWORD),
    ]

def get_all_pids():
    """获取所有 Weixin.exe 进程"""
    import subprocess
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV", "/NH"],
                       capture_output=True, text=True)
    pids = []
    for line in r.stdout.strip().split('\n'):
        if not line.strip():
            continue
        p = line.strip('"').split('","')
        if len(p) >= 5:
            pid = int(p[1])
            mem = int(p[4].replace(',', '').replace(' K', '').strip() or '0')
            pids.append((pid, mem))
    return pids

def read_mem(h, addr, sz):
    buf = ctypes.create_string_buffer(sz)
    n = ctypes.c_size_t(0)
    if kernel32.ReadProcessMemory(h, ctypes.c_uint64(addr), buf, sz, ctypes.byref(n)):
        return buf.raw[:n.value]
    return None

def enum_regions(h):
    regs = []
    addr = 0
    mbi = MBI()
    while addr < 0x7FFFFFFFFFFF:
        if kernel32.VirtualQueryEx(h, ctypes.c_uint64(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)) == 0:
            break
        if mbi.State == MEM_COMMIT and mbi.Protect in READABLE and 0 < mbi.RegionSize < 500*1024*1024:
            regs.append((mbi.BaseAddress, mbi.RegionSize))
        nxt = mbi.BaseAddress + mbi.RegionSize
        if nxt <= addr:
            break
        addr = nxt
    return regs

def verify_key_for_db(enc_key, db_page1):
    """验证 enc_key 是否能解密这个 DB 的 page 1"""
    salt = db_page1[:SALT_SZ]
    iv = db_page1[PAGE_SZ - 80 : PAGE_SZ - 64]
    encrypted = db_page1[SALT_SZ : PAGE_SZ - 80]

    mac_salt = bytes(b ^ 0x3a for b in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=KEY_SZ)
    hmac_data = db_page1[SALT_SZ : PAGE_SZ - 80 + 16]
    stored_hmac = db_page1[PAGE_SZ - 64 : PAGE_SZ]
    h = hmac_mod.new(mac_key, hmac_data, hashlib.sha512)
    h.update(struct.pack('<I', 1))
    return h.digest() == stored_hmac


def main():
    print("=" * 60)
    print("  增强版密钥提取 (扫描所有进程 + salt 字节搜索)")
    print("=" * 60)

    # 1. 收集所有 DB 文件及其 salt
    db_files = []
    salt_to_dbs = {}

    for root, dirs, files in os.walk(DB_DIR):
        for f in files:
            if f.endswith('.db') and not f.endswith('-wal') and not f.endswith('-shm'):
                path = os.path.join(root, f)
                rel = os.path.relpath(path, DB_DIR)
                sz = os.path.getsize(path)
                if sz < PAGE_SZ:
                    continue
                with open(path, 'rb') as fh:
                    page1 = fh.read(PAGE_SZ)
                salt = page1[:SALT_SZ]
                salt_hex = salt.hex()
                db_files.append((rel, path, sz, salt_hex, page1, salt))
                if salt_hex not in salt_to_dbs:
                    salt_to_dbs[salt_hex] = []
                salt_to_dbs[salt_hex].append(rel)

    print(f"\n找到 {len(db_files)} 个数据库, {len(salt_to_dbs)} 个不同的 salt")

    # 2. 获取所有微信进程
    all_pids = get_all_pids()
    if not all_pids:
        print("[ERROR] Weixin.exe 未运行")
        sys.exit(1)

    print(f"找到 {len(all_pids)} 个微信进程:")
    for pid, mem in all_pids:
        print(f"  PID={pid} ({mem//1024}MB)")

    # 准备 salt 字节搜索
    salt_bytes_map = {}  # salt_bytes -> salt_hex
    for rel, path, sz, salt_hex, page1, salt_bytes in db_files:
        salt_bytes_map[salt_bytes] = salt_hex

    # 3. 扫描每个进程
    key_map = {}  # salt_hex -> enc_key_hex
    hex_re = re.compile(b"x'([0-9a-fA-F]{64,192})'")

    for pid, mem_size in all_pids:
        print(f"\n--- 扫描 PID={pid} ({mem_size//1024}MB) ---")

        h = kernel32.OpenProcess(0x0010 | 0x0400, False, pid)
        if not h:
            print(f"  [SKIP] 无法打开进程 (error={ctypes.get_last_error()})")
            continue

        regions = enum_regions(h)
        total_mb = sum(s for _, s in regions) / 1024 / 1024
        print(f"  可读内存: {len(regions)} 区域, {total_mb:.0f}MB")

        t0 = time.time()
        all_hex_matches = 0
        salt_found = 0

        for reg_idx, (base, size) in enumerate(regions):
            data = read_mem(h, base, size)
            if not data:
                continue

            # 方法1: 搜索 x'<hex>' 模式
            for m in hex_re.finditer(data):
                hex_str = m.group(1).decode()
                all_hex_matches += 1
                hex_len = len(hex_str)

                if hex_len == 96:
                    enc_key_hex = hex_str[:64]
                    salt_hex = hex_str[64:]
                    if salt_hex in salt_to_dbs and salt_hex not in key_map:
                        enc_key = bytes.fromhex(enc_key_hex)
                        for rel, path, sz, s, page1, _ in db_files:
                            if s == salt_hex:
                                if verify_key_for_db(enc_key, page1):
                                    key_map[salt_hex] = enc_key_hex
                                    print(f"  [FOUND-x'] salt={salt_hex} -> {rel}")
                                break

                elif hex_len == 64:
                    enc_key_hex = hex_str
                    enc_key = bytes.fromhex(enc_key_hex)
                    for rel, path, sz, salt_hex_db, page1, _ in db_files:
                        if salt_hex_db not in key_map:
                            if verify_key_for_db(enc_key, page1):
                                key_map[salt_hex_db] = enc_key_hex
                                print(f"  [FOUND-x'] salt={salt_hex_db} -> {rel}")
                                break

                elif hex_len > 96 and hex_len % 2 == 0:
                    enc_key_hex = hex_str[:64]
                    salt_hex = hex_str[-32:]
                    if salt_hex in salt_to_dbs and salt_hex not in key_map:
                        enc_key = bytes.fromhex(enc_key_hex)
                        for rel, path, sz, s, page1, _ in db_files:
                            if s == salt_hex:
                                if verify_key_for_db(enc_key, page1):
                                    key_map[salt_hex] = enc_key_hex
                                    print(f"  [FOUND-x'] salt={salt_hex} -> {rel}")
                                break

            # 方法2: 直接搜索 salt 字节
            if len(key_map) < len(salt_to_dbs):
                for salt_bytes, salt_hex in salt_bytes_map.items():
                    if salt_hex in key_map:
                        continue
                    pos = data.find(salt_bytes)
                    while pos != -1:
                        # 在 salt 附近搜索 key (前 64 字节作为 enc_key)
                        # WCDB 格式: enc_key(32B) + salt(16B) 连续存储
                        if pos >= 32:
                            potential_key = data[pos-32:pos]
                            for rel, path, sz, s, page1, _ in db_files:
                                if s == salt_hex:
                                    if verify_key_for_db(potential_key, page1):
                                        key_map[salt_hex] = potential_key.hex()
                                        print(f"  [FOUND-salt] salt={salt_hex} -> {rel}")
                                        salt_found += 1
                                    break

                        # 也尝试 salt 后面的 32 字节
                        if pos + 16 + 32 <= len(data):
                            potential_key = data[pos+16:pos+16+32]
                            for rel, path, sz, s, page1, _ in db_files:
                                if s == salt_hex:
                                    if verify_key_for_db(potential_key, page1):
                                        key_map[salt_hex] = potential_key.hex()
                                        print(f"  [FOUND-salt] salt={salt_hex} -> {rel}")
                                        salt_found += 1
                                    break

                        # 搜索下一个位置
                        pos = data.find(salt_bytes, pos + 1)

            # 进度
            if (reg_idx + 1) % 500 == 0:
                elapsed = time.time() - t0
                progress = sum(s for b, s in regions[:reg_idx+1]) / sum(s for _, s in regions) * 100
                print(f"  [{progress:.1f}%] {len(key_map)}/{len(salt_to_dbs)} salts, "
                      f"{all_hex_matches} hex, {salt_found} salt-matches, {elapsed:.1f}s")

        elapsed = time.time() - t0
        print(f"  扫描完成: {elapsed:.1f}s, {all_hex_matches} hex模式, {salt_found} salt匹配")
        print(f"  本进程找到: {len(key_map)}/{len(salt_to_dbs)} 密钥")

        kernel32.CloseHandle(h)

        if len(key_map) == len(salt_to_dbs):
            print("  所有密钥已找到！")
            break

    # 4. 交叉验证
    missing_salts = set(salt_to_dbs.keys()) - set(key_map.keys())
    if missing_salts and key_map:
        print(f"\n还有 {len(missing_salts)} 个 salt 未匹配，尝试交叉验证...")
        for salt_hex in list(missing_salts):
            for rel, path, sz, s, page1, _ in db_files:
                if s == salt_hex:
                    for known_salt, known_key_hex in key_map.items():
                        enc_key = bytes.fromhex(known_key_hex)
                        if verify_key_for_db(enc_key, page1):
                            key_map[salt_hex] = known_key_hex
                            print(f"  [CROSS] salt={salt_hex} 可用 key from salt={known_salt}")
                            missing_salts.discard(salt_hex)
                    break

    # 5. 输出结果
    print(f"\n{'='*60}")
    print(f"结果: {len(key_map)}/{len(salt_to_dbs)} salts 找到密钥")

    result = {}
    for rel, path, sz, salt_hex, page1, _ in db_files:
        if salt_hex in key_map:
            result[rel] = {
                "enc_key": key_map[salt_hex],
                "salt": salt_hex,
                "size_mb": round(sz/1024/1024, 1)
            }
            print(f"  OK: {rel} ({sz/1024/1024:.1f}MB)")
        else:
            print(f"  MISSING: {rel} (salt={salt_hex})")

    with open(OUT_FILE, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"\n密钥保存到: {OUT_FILE}")

    missing = [rel for rel, path, sz, salt_hex, page1, _ in db_files if salt_hex not in key_map]
    if missing:
        print(f"\n未找到密钥的数据库 ({len(missing)} 个):")
        for rel in missing:
            print(f"  {rel}")
        print("\n提示: 微信 4.x 懒加载数据库密钥。请尝试:")
        print("  1. 在微信中打开几个聊天窗口（点击进入对话）")
        print("  2. 浏览朋友圈")
        print("  3. 查看收藏")
        print("  4. 然后重新运行本脚本")


if __name__ == '__main__':
    main()
