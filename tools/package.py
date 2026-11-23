"""Build a platform ZIP from this checkout. See tools/README.md."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
DATA = ("dictionary.sqlite3", "phrases.json", "ECDICT-LICENSE", "README.md", "THIRD_PARTY.md")
CORE = ("__init__.py", "__main__.py", "core.py", "formatting.py", "profiles.py", "translate.py", "theme.py")
EMBED = "python-3.13.12-embed-amd64.zip"
WX = "wxpython-4.2.3-cp313-cp313-win_amd64.whl"
COM = "comtypes-1.4.12-py3-none-any.whl"
TYPING = "typing_extensions-4.16.0-py3-none-any.whl"
NUMPY = "numpy-2.5.5-cp313-cp313-win_amd64.whl"
HASHES = {
    EMBED: "76f238f606250c87c6beac75dccd35ee99070a13490555936abb6cb64ecce3d0",
    WX: "dac14ea1b04d90b403414f0401704beecae0d3e7143755a20da0ac2cfec02bf9",
    COM: "e0fa9cc19c489fa7feea4c1710f4575c717e2673edef5b99bf99efd507908e44",
    TYPING: "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8",
    NUMPY: "e0608d1585557b68dcb6a70a41654f7536567960afad79d91752d2863b242b68",
}


def add_files(base, dest, names):
    dest.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy2(base / name, dest / name)


def compile_launcher(work, target):
    """Cross-build the native GUI launcher with LLVM and GNU binutils."""
    libraries = []
    for dll, exports in {"kernel32": ["GetModuleFileNameW", "CreateProcessW", "CloseHandle", "ExitProcess"],
                         "user32": ["MessageBoxW"]}.items():
        definition = work / (dll + ".def")
        definition.write_text("LIBRARY " + dll + ".dll\nEXPORTS\n" + "\n".join(exports) + "\n")
        archive = work / ("lib" + dll + ".a")
        subprocess.run(["llvm-dlltool", "-m", "i386:x86-64", "-d", definition, "-l", archive], check=True)
        libraries.append(archive)
    shutil.copy2(ROOT / "hoverling/windows/HoverLing.ico", work / "HoverLing.ico")
    (work / "icon.rc").write_text('1 ICON "HoverLing.ico"\n')
    subprocess.run(["llvm-rc", "/fo", "icon.res", "icon.rc"], cwd=work, check=True)
    subprocess.run(["llvm-cvtres", "/machine:x64", "/out:icon.obj", "icon.res"], cwd=work, check=True)
    subprocess.run(["clang", "--target=x86_64-w64-windows-gnu", "-Os", "-ffreestanding",
                    "-fno-stack-protector", "-c", ROOT / "tools/windows/launcher.c", "-o", "launcher.o"],
                   cwd=work, check=True)
    subprocess.run(["ld", "-m", "i386pep", "--subsystem", "windows", "-e", "start", "-o", target,
                    "launcher.o", "icon.obj", *libraries], cwd=work, check=True)


def add_windows_runtime(cache, runtime):
    for name, expected in HASHES.items():
        path = cache / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SystemExit(f"缺少依赖文件或 SHA-256 不匹配：{path}")
    with ZipFile(cache / EMBED) as archive:
        archive.extractall(runtime)
    for name in (WX, COM, TYPING):
        with ZipFile(cache / name) as archive:
            archive.extractall(runtime / "Lib/site-packages")
    with ZipFile(cache / NUMPY) as archive:
        # wxWidgets links to this redistributable C++ runtime by its original name.
        member, = (n for n in archive.namelist() if n.startswith("numpy.libs/msvcp140-") and n.endswith(".dll"))
        (runtime / "msvcp140.dll").write_bytes(archive.read(member))
    (runtime / "python313._pth").write_text("python313.zip\n.\n..\nLib/site-packages\nimport site\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=("linux", "windows"))
    parser.add_argument("--cache", type=Path, help="Windows 构建依赖压缩包所在目录")
    parser.add_argument("--out", type=Path, default=ROOT / "dist", help="ZIP 输出目录")
    args = parser.parse_args()
    windows = args.platform == "windows"
    if windows and args.cache is None:
        parser.error("Windows 构建需要 --cache，准备方法见 tools/README.md")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    name = "HoverLing-Windows-x64.zip" if windows else "HoverLing-Linux-X11.zip"
    with tempfile.TemporaryDirectory(dir=out) as folder:
        work = Path(folder)
        stage = work / "hoverling"
        package = stage / "hoverling"
        add_files(ROOT, stage, DATA)
        add_files(ROOT / "hoverling", package, CORE)
        if windows:
            shutil.copytree(ROOT / "hoverling/windows", package / "windows",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            add_windows_runtime(args.cache.resolve(), stage / "runtime")
            compile_launcher(work, stage / "HoverLing.exe")
        else:
            add_files(ROOT, stage, ("icon.svg", "install.sh", "launch.sh", "uninstall.sh"))
            add_files(ROOT / "hoverling", package, ("app.py", "tray.py"))
            for directory in ("tessdata", "tests"):
                shutil.copytree(ROOT / directory, stage / directory,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "test_windows_*.py"))
        archive = work / name
        with ZipFile(archive, "w", ZIP_DEFLATED) as zipped:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    zipped.write(path, path.relative_to(work))
        os.replace(archive, out / name)
    print(out / name)


if __name__ == "__main__":
    main()
