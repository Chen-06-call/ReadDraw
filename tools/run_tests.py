"""运行完整测试；可选用继承目录权限的临时目录，兼容受限 Windows 环境。"""

import argparse
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def inherited_temporary_directory(suffix=None, prefix=None, dir=None):
    """仅替换目录创建方式；保留 TemporaryDirectory 的隔离与自动清理行为。

    Python 3.13 在 Windows 上为 mkdtemp 的目录使用私有 ACL，某些沙箱
    会因此拒绝后续访问。普通 mkdir 继承项目目录的权限，仍使用随机目录名。
    """
    base = Path(dir) if dir else ROOT / ".build-deps" / "test-runs"
    base.mkdir(parents=True, exist_ok=True)
    target = base / f"{prefix or 'tmp'}{uuid.uuid4().hex}{suffix or ''}"
    target.mkdir()
    return str(target.resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inherited-temp", action="store_true")
    args = parser.parse_args()
    runner = unittest.TextTestRunner(verbosity=2)
    if args.inherited_temp:
        with patch.object(tempfile, "mkdtemp", inherited_temporary_directory):
            result = runner.run(unittest.defaultTestLoader.discover(str(ROOT / "tests")))
    else:
        result = runner.run(unittest.defaultTestLoader.discover(str(ROOT / "tests")))
    raise SystemExit(0 if result.wasSuccessful() else 1)
