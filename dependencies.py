"""依赖检查与安装模块。

负责检查程序运行所需的 Python 依赖是否已安装、获取版本，
并通过当前解释器的 pip 安装缺失的依赖。
"""
import importlib.metadata
import importlib.util
import subprocess
import sys

# 运行所需的第三方依赖（import_name 用于运行时探测）
REQUIRED_PACKAGES = [
    {"name": "flask", "import_name": "flask", "required": ">=2.3"},
    {"name": "requests", "import_name": "requests", "required": ">=2.28"},
    {"name": "openpyxl", "import_name": "openpyxl", "required": ">=3.1"},
]


def check_dependencies():
    """检查依赖安装状态，返回列表。"""
    results = []
    for r in REQUIRED_PACKAGES:
        installed = importlib.util.find_spec(r["import_name"]) is not None
        version = None
        if installed:
            try:
                version = importlib.metadata.version(r["import_name"])
            except Exception:  # noqa: BLE001
                version = None
        results.append({
            "name": r["name"],
            "import_name": r["import_name"],
            "required": r["required"],
            "installed": installed,
            "version": version,
        })
    return results


def missing_packages():
    """返回尚未安装的依赖包名列表。"""
    return [r["name"] for r in check_dependencies() if not r["installed"]]


def install_packages(packages=None, timeout=600):
    """用当前解释器的 pip 安装依赖，返回 (returncode, stdout, stderr)。"""
    targets = packages or missing_packages()
    if not targets:
        return 0, "所有依赖均已安装，无需操作。", ""
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade"] + list(targets)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "安装超时（超过 %d 秒）" % timeout
    except Exception as e:  # noqa: BLE001
        return -1, "", str(e)
