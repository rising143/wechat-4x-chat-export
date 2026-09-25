"""诊断脚本 - 检查管理员权限下的环境"""
import sys
import os
import json
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
log_path = os.path.join(SCRIPT_DIR, "diagnose_log.txt")

with open(log_path, 'w', encoding='utf-8') as f:
    f.write("=== Admin Environment Diagnostics ===\n")
    f.write(f"Python: {sys.executable}\n")
    f.write(f"Version: {sys.version}\n")
    f.write(f"Platform: {sys.platform}\n")
    f.write(f"Args: {sys.argv}\n")
    f.write(f"CWD: {os.getcwd()}\n")
    f.write(f"SCRIPT_DIR: {SCRIPT_DIR}\n")
    f.write(f"SCRIPT_DIR exists: {os.path.exists(SCRIPT_DIR)}\n")

    # 列出目录内容
    try:
        files = os.listdir(SCRIPT_DIR)
        f.write(f"Files in dir ({len(files)}): {files[:30]}\n")
    except Exception as e:
        f.write(f"List dir error: {e}\n")

    # 检查管理员权限
    try:
        import ctypes
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
        f.write(f"IsAdmin: {is_admin}\n")
    except Exception as e:
        f.write(f"Admin check error: {e}\n")

    # 检查 config.json
    config_path = os.path.join(SCRIPT_DIR, 'config.json')
    f.write(f"Config path: {config_path}\n")
    f.write(f"Config exists: {os.path.exists(config_path)}\n")
    try:
        with open(config_path, encoding='utf-8') as cf:
            cfg = json.load(cf)
        f.write(f"Config loaded OK: {cfg}\n")
    except Exception as e:
        f.write(f"Config error: {e}\n")
        traceback.print_exc(file=f)

    # 检查 deep_key_search.py
    script_path = os.path.join(SCRIPT_DIR, 'deep_key_search.py')
    f.write(f"Script exists: {os.path.exists(script_path)}\n")
    try:
        with open(script_path, encoding='utf-8') as sf:
            code = sf.read()
        f.write(f"Script read OK, length={len(code)}\n")
    except Exception as e:
        f.write(f"Script read error: {e}\n")

    # 检查依赖
    try:
        from Crypto.Cipher import AES
        f.write("pycryptodome: OK\n")
    except Exception as e:
        f.write(f"pycryptodome: FAIL - {e}\n")

    try:
        import zstandard
        f.write(f"zstandard: OK ({zstandard.__version__})\n")
    except Exception as e:
        f.write(f"zstandard: FAIL - {e}\n")

    # 检查数据库目录
    try:
        db_dir = cfg.get('db_dir', '')
        f.write(f"DB dir: {db_dir}\n")
        f.write(f"DB dir exists: {os.path.exists(db_dir)}\n")
        if os.path.exists(db_dir):
            db_files = [f for f in os.listdir(db_dir) if f.endswith('.db')]
            f.write(f"DB files: {db_files[:20]}\n")
    except Exception as e:
        f.write(f"DB dir check error: {e}\n")

    # 尝试编译脚本
    try:
        with open(script_path, encoding='utf-8') as sf:
            code = sf.read()
        compile(code, script_path, 'exec')
        f.write("Script compile: OK\n")
    except SyntaxError as e:
        f.write(f"Script compile error: {e}\n")
        f.write(f"  Line: {e.lineno}, Offset: {e.offset}\n")
        f.write(f"  Text: {e.text}\n")
    except Exception as e:
        f.write(f"Script compile error: {e}\n")

    f.write("=== Diagnostics Done ===\n")

print("Diagnostics written to:", log_path)
