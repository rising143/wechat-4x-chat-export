"""
以管理员权限运行 DbkeyHookCMD 提取微信数据库密钥
"""
import ctypes
import subprocess
import os
import sys
import time

def check_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def main():
    exe_dir = os.path.dirname(os.path.abspath(__file__))
    dbkey_exe = os.path.join(exe_dir, "DbkeyHookCMD.exe")
    output_file = os.path.join(exe_dir, "dbkey_result.txt")

    # 获取微信 PID
    import ctypes.wintypes as wt
    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
            ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
            ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)

    pids = []
    if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
        while True:
            if entry.szExeFile.lower() == 'weixin.exe':
                pids.append((entry.th32ProcessID, entry.cntThreads))
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snapshot)

    if not pids:
        print("[ERROR] 未找到微信进程")
        return

    # 选择线程最多的进程作为主进程
    pid = max(pids, key=lambda x: x[1])[0]
    print(f"微信主进程 PID: {pid}")
    print(f"所有微信进程: {pids}")

    # 运行 DbkeyHookCMD
    cmd = [dbkey_exe, "-pid", str(pid), "-r"]
    print(f"运行命令: {' '.join(cmd)}")

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"=== DbkeyHookCMD Run ===\n")
        f.write(f"PID: {pid}\n")
        f.write(f"Command: {' '.join(cmd)}\n")
        f.write(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"--- Output ---\n")
        f.flush()

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        f.write(f"STDOUT:\n{proc.stdout}\n")
        f.write(f"STDERR:\n{proc.stderr}\n")
        f.write(f"ExitCode: {proc.returncode}\n")
        f.write(f"--- End ---\n")

    print(f"\n输出已保存到: {output_file}")
    print(f"退出码: {proc.returncode}")

    if proc.stdout:
        print(f"\nSTDOUT:\n{proc.stdout}")
    if proc.stderr:
        print(f"\nSTDERR:\n{proc.stderr}")

    # 检查是否生成了密钥文件
    for f_name in os.listdir(exe_dir):
        if f_name.endswith('.json') and f_name != 'config.json' and f_name != 'config.example.json':
            f_path = os.path.join(exe_dir, f_name)
            mtime = os.path.getmtime(f_path)
            if mtime > time.time() - 120:  # 2分钟内修改的
                print(f"\n[发现新文件] {f_name}")
                with open(f_path, 'r') as rf:
                    content = rf.read()
                    print(f"内容: {content[:500]}")

if __name__ == '__main__':
    if not check_admin():
        print("[!] 需要管理员权限，正在请求提升...")
        print("    请在弹出的UAC对话框中点击'是'")
        script_path = os.path.abspath(__file__)
        params = f'"{script_path}"'
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, os.path.dirname(script_path), 1)
    else:
        print("[OK] 管理员权限")
        main()
        input("\n按回车键退出...")
