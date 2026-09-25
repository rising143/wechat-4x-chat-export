"""
诊断脚本 - 检查微信进程内存中是否存在各种可能的密钥格式
"""
import ctypes
import ctypes.wintypes as wt
import struct, os, sys, hashlib, re, json
import subprocess

kernel32 = ctypes.windll.kernel32
MEM_COMMIT = 0x1000
READABLE = {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80}
PAGE_SZ = 4096
SALT_SZ = 16

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(SCRIPT_DIR, "config.json")) as f:
    _cfg = json.load(f)
DB_DIR = _cfg["db_dir"]

class MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_uint64), ("AllocationBase", ctypes.c_uint64),
        ("AllocationProtect", wt.DWORD), ("_pad1", wt.DWORD),
        ("RegionSize", ctypes.c_uint64), ("State", wt.DWORD),
        ("Protect", wt.DWORD), ("Type", wt.DWORD), ("_pad2", wt.DWORD),
    ]

def get_all_pids():
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

# 收集 salt
salts_hex = []
salts_bytes = []
for root, dirs, files in os.walk(DB_DIR):
    for f in files:
        if f.endswith('.db') and not f.endswith('-wal') and not f.endswith('-shm'):
            path = os.path.join(root, f)
            if os.path.getsize(path) < PAGE_SZ:
                continue
            with open(path, 'rb') as fh:
                page1 = fh.read(PAGE_SZ)
            salt = page1[:SALT_SZ]
            salts_hex.append(salt.hex())
            salts_bytes.append(salt)

print("=" * 60)
print("  微信进程内存诊断")
print("=" * 60)
print(f"\n数据库 salt 列表 ({len(salts_hex)} 个):")
for sh in salts_hex[:5]:
    print(f"  {sh}")
print(f"  ... (共 {len(salts_hex)} 个)")

all_pids = get_all_pids()
print(f"\n微信进程 ({len(all_pids)} 个):")
for pid, mem in all_pids:
    print(f"  PID={pid} ({mem//1024}MB)")

# 扫描主进程
pid, mem_size = max(all_pids, key=lambda x: x[1])
print(f"\n--- 诊断主进程 PID={pid} ({mem_size//1024}MB) ---")

h = kernel32.OpenProcess(0x0010 | 0x0400, False, pid)
if not h:
    print(f"[ERROR] 无法打开进程 (error={ctypes.get_last_error()})")
    sys.exit(1)

regions = enum_regions(h)
total_mb = sum(s for _, s in regions) / 1024 / 1024
print(f"可读内存: {len(regions)} 区域, {total_mb:.0f}MB")

# 统计各种模式
stats = {
    "x_hex_pattern": 0,        # x'<hex>'
    "hex_64": 0,               # 64字符 hex 字符串
    "hex_96": 0,               # 96字符 hex 字符串
    "salt_hex_found": [],      # 找到的 salt hex 字符串
    "salt_bytes_found": 0,     # 找到的 salt 原始字节
    "pragma_key": 0,           # PRAGMA key
    "sqlcipher": 0,            # sqlcipher 相关
    "wcdb": 0,                 # WCDB 相关
    "enc_key": 0,              # enc_key 字符串
    "raw_key": 0,              # raw key 字符串
    "total_data_read": 0,      # 总读取数据量
}

# 搜索模式
x_hex_re = re.compile(b"x'([0-9a-fA-F]{64,192})'")
hex_64_re = re.compile(b"[0-9a-fA-F]{64}")  # 64个连续hex字符
hex_96_re = re.compile(b"[0-9a-fA-F]{96}")  # 96个连续hex字符

for reg_idx, (base, size) in enumerate(regions):
    data = read_mem(h, base, size)
    if not data:
        continue
    stats["total_data_read"] += len(data)

    # x'<hex>' 模式
    for m in x_hex_re.finditer(data):
        stats["x_hex_pattern"] += 1

    # 纯 hex 字符串 (不包含 x'...' 包裹)
    for m in hex_64_re.finditer(data):
        stats["hex_64"] += 1
        # 检查是否包含 salt
        hex_str = m.group().decode('ascii')
        for sh in salts_hex:
            if sh in hex_str:
                stats["salt_hex_found"].append({
                    "salt": sh,
                    "hex_context": hex_str[:128],
                    "address": hex(base + m.start())
                })

    for m in hex_96_re.finditer(data):
        stats["hex_96"] += 1

    # salt 原始字节
    for salt_bytes in salts_bytes:
        pos = data.find(salt_bytes)
        while pos != -1:
            stats["salt_bytes_found"] += 1
            # 打印上下文
            ctx_start = max(0, pos - 16)
            ctx_end = min(len(data), pos + 48)
            context = data[ctx_start:ctx_end]
            print(f"  [SALT BYTES] at 0x{base+pos:016X}: {context.hex()}")
            pos = data.find(salt_bytes, pos + 1)

    # 关键字符串
    for pattern, key in [(b"PRAGMA key", "pragma_key"),
                          (b"sqlcipher", "sqlcipher"),
                          (b"wcdb", "wcdb"),
                          (b"WCDB", "wcdb"),
                          (b"enc_key", "enc_key"),
                          (b"raw_key", "raw_key"),
                          (b"cipher_compatibility", "sqlcipher")]:
        count = data.count(pattern)
        stats[key] += count

kernel32.CloseHandle(h)

print(f"\n--- 诊断结果 ---")
print(f"总读取数据: {stats['total_data_read']/1024/1024:.0f} MB")
print(f"x'<hex>' 模式: {stats['x_hex_pattern']}")
print(f"64字符 hex 字符串: {stats['hex_64']}")
print(f"96字符 hex 字符串: {stats['hex_96']}")
print(f"salt 原始字节匹配: {stats['salt_bytes_found']}")
print(f"salt hex 字符串匹配: {len(stats['salt_hex_found'])}")
print(f"PRAGMA key: {stats['pragma_key']}")
print(f"sqlcipher: {stats['sqlcipher']}")
print(f"wcdb/WCDB: {stats['wcdb']}")
print(f"enc_key: {stats['enc_key']}")
print(f"raw_key: {stats['raw_key']}")

if stats['salt_hex_found']:
    print(f"\n找到 salt hex 字符串:")
    for item in stats['salt_hex_found'][:10]:
        print(f"  salt={item['salt']}")
        print(f"  hex={item['hex_context']}")
        print(f"  addr={item['address']}")
        print()

if stats['x_hex_pattern'] == 0 and stats['salt_bytes_found'] == 0:
    print("\n[诊断] 未找到任何密钥相关模式。")
    print("可能原因:")
    print("  1. 微信懒加载：请打开几个聊天窗口后重新运行")
    print("  2. WeChat 4.1.11.55 可能使用了新的密钥存储格式")
    print("  3. 密钥可能存储在受保护内存区域中")
    if stats['hex_64'] > 0:
        print(f"\n但发现了 {stats['hex_64']} 个 64字符 hex 字符串")
        print("这些可能包含密钥，但格式不同")
