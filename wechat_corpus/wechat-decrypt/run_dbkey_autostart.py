"""
以管理员权限运行 DbkeyHookCMD (自动启动微信模式)
不带 -r 参数，让工具自动启动微信并在初始化时挂钩密钥获取函数
"""
import ctypes
import subprocess
import os
import sys
import time
import functools

print = functools.partial(print, flush=True)

def check_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def main():
    exe_dir = os.path.dirname(os.path.abspath(__file__))
    dbkey_exe = os.path.join(exe_dir, "DbkeyHookCMD.exe")
    output_file = os.path.join(exe_dir, "dbkey_output.txt")
    wx_dir = r"C:\personalsoftware\Weixin"

    print("=" * 60)
    print("  DbkeyHookCMD 自动启动微信模式")
    print("=" * 60)
    print(f"工具路径: {dbkey_exe}")
    print(f"微信目录: {wx_dir}")
    print(f"输出文件: {output_file}")
    print()

    # 不带 -r 参数运行，让工具自动启动微信
    cmd = [dbkey_exe]
    print(f"运行命令: {dbkey_exe}")
    print()
    print(">>> 微信将自动启动，请在微信窗口中登录您的账号 <<<")
    print(">>> 登录后工具会自动捕获数据库密钥 <<<")
    print()

    # 写入头部信息
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"=== DbkeyHookCMD Auto-Start Run ===\n")
        f.write(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Command: {dbkey_exe} (no -r flag, auto-start WeChat)\n")
        f.write(f"--- Output ---\n")
        f.flush()

    # 运行 DbkeyHookCMD，设置较长超时（5分钟，用户需要时间登录）
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5分钟超时
            cwd=exe_dir
        )

        with open(output_file, 'a', encoding='utf-8') as f:
            f.write(f"\nSTDOUT:\n{proc.stdout}\n")
            f.write(f"STDERR:\n{proc.stderr}\n")
            f.write(f"ExitCode: {proc.returncode}\n")
            f.write(f"--- End ---\n")
            f.write(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

        print(f"\nDbkeyHookCMD 退出码: {proc.returncode}")
        if proc.stdout:
            print(f"\n=== STDOUT ===\n{proc.stdout}")
        if proc.stderr:
            print(f"\n=== STDERR ===\n{proc.stderr}")

    except subprocess.TimeoutExpired:
        with open(output_file, 'a', encoding='utf-8') as f:
            f.write(f"\n[TIMEOUT] DbkeyHookCMD 运行超过5分钟，被终止\n")
        print("[TIMEOUT] DbkeyHookCMD 运行超过5分钟")
    except Exception as e:
        with open(output_file, 'a', encoding='utf-8') as f:
            f.write(f"\n[ERROR] {e}\n")
        print(f"[ERROR] {e}")

    # 检查微信目录下是否有 dbkey.txt
    print("\n--- 检查密钥文件 ---")
    dbkey_txt = os.path.join(wx_dir, "dbkey.txt")
    if os.path.exists(dbkey_txt):
        print(f"[FOUND] 微信目录下找到 dbkey.txt!")
        with open(dbkey_txt, 'r') as f:
            key_content = f.read()
        print(f"内容: {key_content}")

        # 复制到我们的目录
        import shutil
        dest = os.path.join(exe_dir, "dbkey.txt")
        shutil.copy2(dbkey_txt, dest)
        print(f"已复制到: {dest}")

        with open(output_file, 'a', encoding='utf-8') as f:
            f.write(f"\n=== dbkey.txt 内容 ===\n{key_content}\n")
    else:
        print(f"微信目录下未找到 dbkey.txt: {dbkey_txt}")

    # 检查当前目录下是否有 dbkey.txt
    local_dbkey = os.path.join(exe_dir, "dbkey.txt")
    if os.path.exists(local_dbkey):
        print(f"[FOUND] 当前目录下找到 dbkey.txt!")
        with open(local_dbkey, 'r') as f:
            print(f"内容: {f.read()}")

    # 检查是否有新生成的文件
    print("\n--- 检查新生成文件 ---")
    for f_name in os.listdir(exe_dir):
        f_path = os.path.join(exe_dir, f_name)
        if os.path.isfile(f_path):
            mtime = os.path.getmtime(f_path)
            if mtime > time.time() - 300:  # 5分钟内修改的
                print(f"  [近期修改] {f_name} ({os.path.getsize(f_path)} bytes)")

    # 也检查微信目录
    for f_name in os.listdir(wx_dir):
        f_path = os.path.join(wx_dir, f_name)
        if os.path.isfile(f_path):
            mtime = os.path.getmtime(f_path)
            if mtime > time.time() - 300 and f_name.endswith('.txt'):
                print(f"  [微信目录-近期修改] {f_name} ({os.path.getsize(f_path)} bytes)")
                try:
                    with open(f_path, 'r', errors='ignore') as rf:
                        content = rf.read()
                    if len(content) < 500:
                        print(f"    内容: {content}")
                except:
                    pass

    print(f"\n输出已保存到: {output_file}")

if __name__ == '__main__':
    if not check_admin():
        print("[!] 需要管理员权限，正在请求提升...")
        print("    请在弹出的UAC对话框中点击'是'")
        script_path = os.path.abspath(__file__)
        params = f'"{script_path}"'
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, os.path.dirname(script_path), 1)
        if ret <= 32:
            print(f"[ERROR] 无法提升权限 (错误码: {ret})")
            print("请右键点击此脚本，选择'以管理员身份运行'")
    else:
        print("[OK] 管理员权限已确认")
        try:
            main()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"\n[FATAL] 脚本崩溃: {e}")
        input("\n按回车键退出...")
