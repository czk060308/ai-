"""提交前检查暂存内容；只报告文件名，不输出任何匹配到的凭证。

既检查不应入库的目录，也将本机.env中的真实凭证与暂存文件比对。
用法：在仓库根目录执行app/.venv/Scripts/python.exe -E app/scripts/check_staged.py。
"""

import re
import subprocess
from pathlib import Path, PurePosixPath

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_DIRS = {'.venv', 'node_modules', 'runtime', 'dist', '__pycache__', '.pytest_cache', 'test-results', 'playwright-report', 'outputs'}
TOKEN_PATTERN = re.compile(rb'(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)')


def git(*arguments: str) -> bytes:
    return subprocess.check_output(['git', *arguments], cwd=ROOT, stderr=subprocess.DEVNULL)


def main():
    # 凭证只在内存中比对，不写入日志、退出消息或报告文件。
    values = dotenv_values(ROOT / 'app' / '.env')
    secrets = [value.encode('utf-8') for key, value in values.items()
               if re.search(r'(?:KEY|TOKEN|SECRET|PASSWORD)', key) and value and len(value) >= 8]
    names = git('diff', '--cached', '--name-only', '--diff-filter=ACM', '-z').decode('utf-8').split('\0')
    names = [name for name in names if name]
    failures = []
    for name in names:
        path = PurePosixPath(name)
        private_env = (path.name == '.env' or path.name.startswith('.env.')) and path.name != '.env.example'
        if private_env or any(part in FORBIDDEN_DIRS for part in path.parts):
            failures.append((name, 'local-only file'))
            continue
        data = git('show', ':' + name)
        if any(secret in data for secret in secrets) or TOKEN_PATTERN.search(data):
            failures.append((name, 'possible credential'))
    for name, reason in failures:
        print(f'BLOCKED: {name} ({reason})')
    if failures:
        raise SystemExit(1)
    print(f'PASS: {len(names)} staged files checked; no local runtime files or detected credentials.')


if __name__ == '__main__':
    main()
