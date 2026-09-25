"""
深度密钥搜索 - 在 salt 附近大范围搜索有效密钥

WeChat 4.1.11.55 不使用 x'<hex>' 格式存储密钥。
本脚本在每处 salt 匹配周围 ±2048 字节范围内，
以 1 字节步长搜索所有可能的 32 字节密钥组合。

优化: 不保存整个内存区域数据，只读取 salt 附近的数据，大幅减少内存使用。
"""
import ctypes
import ctypes.wintypes as wt
import struct, os, sys, hashlib, json, time
import hmac as hmac_mod
import subprocess
import functools

print = functools.partial(print, flush=True)

kernel32 = ctypes.windll.kernel32
MEM_COMMIT = 0x1000
READABLE = {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80}
PAGE_SZ = 4096
KEY_SZ = 32
SALT_SZ = 16

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(SCRIPT_DIR, "config.json")) as f:
    _cfg = json.load(f)
DB_DIR = _cfg["db_dir"]
OUT_FILE = os.path.join(SCRIPT_DIR, "all_keys.json")

class _TeeWriter:
    """同时输出到控制台和日志文件"""
    def __init__(self, *writers):
        self.writers = writers
    def write(self, data):
        for w in self.writers:
            try:
                w.write(data)
                w.flush()
            except:
                pass
    def flush(self):
        for w in self.writers:
            try:
                w.flush()
            except:
                pass

def setup_logging():
    """设置日志输出到文件"""
    log_path = os.path.join(SCRIPT_DIR, "deep_search_log.txt")
    log_file = open(log_path, 'w', encoding='utf-8')
    sys.stdout = _TeeWriter(sys.stdout, log_file)
    sys.stderr = _TeeWriter(sys.stderr, log_file)


class MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_uint64), ("AllocationBase", ctypes.c_uint64),
        ("AllocationProtect", wt.DWORD), ("_pad1", wt.DWORD),
        ("RegionSize", ctypes.c_uint64), ("State", wt.DWORD),
        ("Protect", wt.DWORD), ("Type", wt.DWORD), ("_pad2", wt.DWORD),
    ]


def get_all_pids():
    """使用 Windows ToolHelp32 API 直接枚举 Weixin.exe 进程"""
    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD),
            ("cntUsage", wt.DWORD),
            ("th32ProcessID", wt.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wt.DWORD),
            ("cntThreads", wt.DWORD),
            ("th32ParentProcessID", wt.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wt.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wt.DWORD),
            ("PageFaultCount", wt.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    pids = []
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == 0xFFFFFFFF:
        return pids

    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)

    psapi = ctypes.windll.psapi

    if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
        while True:
            if entry.szExeFile.lower() == 'weixin.exe':
                pid = entry.th32ProcessID
                # 获取内存使用
                proc_handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
                mem = 0
                if proc_handle:
                    counters = PROCESS_MEMORY_COUNTERS()
                    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
                    if psapi.GetProcessMemoryInfo(proc_handle, ctypes.byref(counters), ctypes.sizeof(counters)):
                        mem = counters.WorkingSetSize
                    kernel32.CloseHandle(proc_handle)
                pids.append((pid, mem))

            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break

    kernel32.CloseHandle(snapshot)
    return pids


def check_admin():
    """检查是否有管理员权限"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


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


def verify_key(enc_key, salt, page1):
    """快速 HMAC 验证 (不完整解密，只验证 page 1 的 HMAC)"""
    mac_salt = bytes(b ^ 0x3a for b in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=KEY_SZ)
    hmac_data = page1[SALT_SZ : PAGE_SZ - 80 + 16]
    stored_hmac = page1[PAGE_SZ - 64 : PAGE_SZ]
    h = hmac_mod.new(mac_key, hmac_data, hashlib.sha512)
    h.update(struct.pack('<I', 1))
    return h.digest() == stored_hmac


def main():
    # 检查管理员权限
    if not check_admin():
        print("[!] 当前没有管理员权限，无法读取微信进程内存")
        sys.exit(1)

    # 设置日志输出到文件
    setup_logging()

    print("=" * 60)
    print("  深度密钥搜索 (salt 附近 ±2048 字节)")
    print("=" * 60)

    print("[OK] 管理员权限")

    # 收集数据库信息
    db_info = {}  # salt_hex -> {rel, path, page1, salt_bytes}
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
                db_info[salt_hex] = {
                    'rel': rel,
                    'path': path,
                    'size': sz,
                    'page1': page1,
                    'salt': salt,
                }

    print(f"\n数据库: {len(db_info)} 个 (不同 salt)")

    all_pids = get_all_pids()
    if not all_pids:
        print("[ERROR] 无法找到微信进程")
        sys.exit(1)

    pid, mem = max(all_pids, key=lambda x: x[1])
    print(f"主进程: PID={pid} ({mem//1024//1024}MB)")

    h = kernel32.OpenProcess(0x0010 | 0x0400, False, pid)
    if not h:
        print(f"[ERROR] 无法打开进程 (错误码: {ctypes.GetLastError()})")
        sys.exit(1)

    regions = enum_regions(h)
    print(f"可读内存: {len(regions)} 区域, {sum(s for _, s in regions)/1024/1024:.0f}MB")

    # 第一步: 收集所有 salt 在内存中的位置 (不保存完整数据以节省内存)
    print("\n--- 搜索 salt 位置 ---")
    salt_locations = []  # [(region_base, offset_in_region, salt_hex)]
    salt_bytes_map = {salt_hex: info['salt'] for salt_hex, info in db_info.items()}

    for reg_idx, (base, size) in enumerate(regions):
        data = read_mem(h, base, size)
        if not data:
            continue
        for salt_hex, salt_bytes in salt_bytes_map.items():
            pos = data.find(salt_bytes)
            while pos != -1:
                salt_locations.append((base, pos, salt_hex))
                pos = data.find(salt_bytes, pos + 1)

        if (reg_idx + 1) % 200 == 0:
            print(f"  已扫描 {reg_idx+1}/{len(regions)} 区域, {len(salt_locations)} 处 salt 匹配")

    print(f"找到 {len(salt_locations)} 处 salt 匹配")

    if not salt_locations:
        print("\n[!] 未找到任何 salt 匹配")
        print("    可能原因: 微信刚启动，数据库尚未加载到内存")
        print("    建议: 在微信中打开一些聊天窗口，然后重新运行")
        kernel32.CloseHandle(h)
        sys.exit(1)

    # 第二步: 在每处 salt 附近搜索密钥
    print("\n--- 在 salt 附近搜索密钥 ---")
    SEARCH_RANGE = 2048  # 搜索范围 ±2048 字节
    key_map = {}  # salt_hex -> enc_key_hex
    candidates_tested = 0

    t0 = time.time()
    for i, (base, salt_pos, salt_hex) in enumerate(salt_locations):
        if salt_hex in key_map:
            continue

        info = db_info[salt_hex]
        page1 = info['page1']
        salt = info['salt']

        # 只读取 salt 附近的数据 (±2048 字节)，不保存整个区域
        search_start = max(0, salt_pos - SEARCH_RANGE)
        search_end = salt_pos + SALT_SZ + SEARCH_RANGE
        read_size = search_end - search_start

        data = read_mem(h, base + search_start, read_size)
        if not data:
            continue

        # salt 在读取数据中的偏移
        local_salt_pos = salt_pos - search_start

        # 以 1 字节步长搜索
        for offset in range(0, len(data) - KEY_SZ):
            # 跳过 salt 本身
            if local_salt_pos - KEY_SZ <= offset <= local_salt_pos + SALT_SZ:
                continue

            candidate = data[offset:offset + KEY_SZ]
            candidates_tested += 1

            # 快速过滤: 全零或全 0xFF 的跳过
            if candidate == b'\x00' * 32 or candidate == b'\xff' * 32:
                continue

            if verify_key(candidate, salt, page1):
                key_map[salt_hex] = candidate.hex()
                addr = base + search_start + offset
                print(f"  [FOUND] {info['rel']}")
                print(f"    key={candidate.hex()}")
                print(f"    salt={salt_hex}")
                print(f"    addr=0x{addr:016X} (offset from salt: {offset - local_salt_pos})")
                break

        if (i + 1) % 10 == 0:
            elapsed = time.time() - t0
            print(f"  进度: {i+1}/{len(salt_locations)}, "
                  f"已找到 {len(key_map)}/{len(db_info)}, "
                  f"测试 {candidates_tested} 个候选 ({elapsed:.1f}s)")

    elapsed = time.time() - t0
    print(f"\n搜索完成: {elapsed:.1f}s, 测试 {candidates_tested} 个候选")
    print(f"找到 {len(key_map)}/{len(db_info)} 个密钥")

    # 交叉验证
    missing = set(db_info.keys()) - set(key_map.keys())
    if missing and key_map:
        print(f"\n交叉验证 {len(missing)} 个未匹配的 salt...")
        for salt_hex in list(missing):
            info = db_info[salt_hex]
            for known_salt, known_key_hex in key_map.items():
                enc_key = bytes.fromhex(known_key_hex)
                if verify_key(enc_key, info['salt'], info['page1']):
                    key_map[salt_hex] = known_key_hex
                    print(f"  [CROSS] {info['rel']} <- key from {db_info[known_salt]['rel']}")
                    missing.discard(salt_hex)
                    break

    # 输出结果
    print(f"\n{'='*60}")
    print(f"结果: {len(key_map)}/{len(db_info)} 密钥找到")

    result = {}
    for salt_hex, info in db_info.items():
        rel = info['rel']
        if salt_hex in key_map:
            result[rel] = {
                "enc_key": key_map[salt_hex],
                "salt": salt_hex,
                "size_mb": round(info['size'] / 1024 / 1024, 1)
            }
            print(f"  OK: {rel}")
        else:
            print(f"  MISSING: {rel}")

    with open(OUT_FILE, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"\n密钥保存到: {OUT_FILE}")

    kernel32.CloseHandle(h)


if __name__ == '__main__':
    if not check_admin():
        print("[!] 需要管理员权限，正在请求提升...")
        print("    请在弹出的UAC对话框中点击'是'")
        script_path = os.path.abspath(__file__)
        params = f'"{script_path}"'
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, SCRIPT_DIR, 1)
    else:
        try:
            main()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"\n[FATAL] 脚本崩溃: {e}")
            input("\n按回车键退出...")
