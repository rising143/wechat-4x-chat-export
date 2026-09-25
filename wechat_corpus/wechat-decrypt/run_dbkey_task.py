"""
通过 Windows 计划任务以最高权限运行 DbkeyHookCMD
计划任务可以绕过 UAC 交互，直接以管理员权限运行程序
"""
import ctypes
import subprocess
import os
import sys
import time
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DBKEY_EXE = os.path.join(SCRIPT_DIR, "DbkeyHookCMD.exe")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "dbkey_task_output.txt")
TASK_NAME = "DbkeyHookRun"

def check_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def main():
    print("=" * 60)
    print("  通过计划任务运行 DbkeyHookCMD")
    print("=" * 60)

    # 清理旧的输出文件
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)

    # 创建计划任务
    print("\n[1] 创建计划任务...")

    # 使用 PowerShell 创建计划任务
    ps_script = f'''
$action = New-ScheduledTaskAction -Execute "{DBKEY_EXE}"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(3)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\\$env:USERNAME" -RunLevel Highest -LogonType Interactive
Register-ScheduledTask -TaskName "{TASK_NAME}" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
'''

    result = subprocess.run(
        ["powershell", "-Command", ps_script],
        capture_output=True, text=True, timeout=30
    )

    if result.returncode != 0:
        print(f"[ERROR] 创建计划任务失败:")
        print(f"  stderr: {result.stderr}")
        print(f"  stdout: {result.stdout}")
        return False

    print("[OK] 计划任务已创建")

    # 等待任务触发
    print("\n[2] 等待任务触发 (3秒)...")
    time.sleep(5)

    # 运行任务
    print("\n[3] 手动触发任务...")
    result = subprocess.run(
        ["powershell", "-Command", f"Start-ScheduledTask -TaskName '{TASK_NAME}'"],
        capture_output=True, text=True, timeout=10
    )

    print("[OK] 任务已触发")
    print("\n" + "=" * 60)
    print("  DbkeyHookCMD 正在以管理员权限运行")
    print("  微信将自动启动，请在微信中登录您的账号")
    print("  登录后工具会自动捕获密钥")
    print("=" * 60)

    # 等待任务完成 (最多5分钟)
    print("\n[4] 等待任务完成 (最多5分钟)...")
    for i in range(300):
        time.sleep(1)

        # 检查任务状态
        result = subprocess.run(
            ["powershell", "-Command", f"(Get-ScheduledTaskInfo -TaskName '{TASK_NAME}').LastTaskResult"],
            capture_output=True, text=True, timeout=5
        )
        status = result.stdout.strip()

        # 检查是否有输出
        if os.path.exists(OUTPUT_FILE):
            with open(OUTPUT_FILE, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            if content.strip():
                print(f"\n[FOUND] 输出文件有内容!")
                print(content)

                # 检查是否包含密钥
                import re
                match = re.search(r'([0-9a-fA-F]{64})', content)
                if match:
                    passphrase = match.group(1)
                    print(f"\n{'='*60}")
                    print(f"  密钥已找到!")
                    print(f"  Passphrase: {passphrase}")
                    print(f"{'='*60}")

                    # 保存密钥
                    with open(os.path.join(SCRIPT_DIR, "dbkey.txt"), 'w') as f:
                        f.write(passphrase)
                    print("密钥已保存到 dbkey.txt")
                    break

        # 检查微信是否在运行
        try:
            wx_result = subprocess.run(
                ["powershell", "-Command", "(Get-Process Weixin -ErrorAction SilentlyContinue).Count"],
                capture_output=True, text=True, timeout=5
            )
            wx_count = int(wx_result.stdout.strip()) if wx_result.stdout.strip() else 0
        except:
            wx_count = 0

        if i % 10 == 0:
            print(f"  [{i}s] 任务状态: {status}, 微信进程: {wx_count}")

        # 如果任务已完成且微信已关闭
        if status == "0" and wx_count == 0 and i > 10:
            print(f"\n[INFO] 任务已完成 (退出码: {status})")

            # 检查 dbkey.txt
            dbkey_paths = [
                os.path.join(SCRIPT_DIR, "dbkey.txt"),
                r"C:\personalsoftware\Weixin\dbkey.txt",
            ]
            for p in dbkey_paths:
                if os.path.exists(p):
                    with open(p, 'r') as f:
                        key = f.read().strip()
                    print(f"\n[FOUND] dbkey.txt: {p}")
                    print(f"  密钥: {key}")

                    # 复制到脚本目录
                    if p != os.path.join(SCRIPT_DIR, "dbkey.txt"):
                        import shutil
                        shutil.copy2(p, os.path.join(SCRIPT_DIR, "dbkey.txt"))
                    break
            break

    # 清理计划任务
    print("\n[5] 清理计划任务...")
    subprocess.run(
        ["powershell", "-Command", f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false"],
        capture_output=True, text=True, timeout=10
    )
    print("[OK] 计划任务已清理")

    # 最终检查
    print("\n" + "=" * 60)
    print("  最终检查")
    print("=" * 60)

    for p in [os.path.join(SCRIPT_DIR, "dbkey.txt"),
              r"C:\personalsoftware\Weixin\dbkey.txt"]:
        if os.path.exists(p):
            with open(p, 'r') as f:
                key = f.read().strip()
            if key:
                print(f"\n密钥文件: {p}")
                print(f"密钥内容: {key}")
                return True

    print("\n[WARNING] 未找到密钥文件")
    print("请检查 DbkeyHookCMD 的输出或手动运行工具")
    return False

if __name__ == '__main__':
    if not check_admin():
        print("[!] 需要管理员权限，正在请求提升...")
        script_path = os.path.abspath(__file__)
        params = f'"{script_path}"'
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, SCRIPT_DIR, 1)
        if ret <= 32:
            print(f"[ERROR] 无法提升权限 (错误码: {ret})")
            print("\n请手动右键此脚本 → 以管理员身份运行")
            sys.exit(1)
    else:
        print("[OK] 管理员权限")
        success = main()
        if success:
            print("\n\n✓ 密钥提取成功！可以继续解密数据库。")
        else:
            print("\n\n✗ 密钥提取失败。请尝试手动运行 DbkeyHookUI.exe")
        input("\n按回车键退出...")
