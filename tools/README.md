# 从同一份源码构建

在仓库根目录操作。两种包都读取 `hoverling/` 中的翻译模块、根目录的词典和短语文件。Linux 的桌面入口是 `hoverling/app.py`，Windows 的桌面入口是 `hoverling/windows/app.py`。运行 `python -m hoverling` 会按当前系统选择入口。

### 源码运行

- Linux X11 安装主 README 所列依赖后运行 `bash launch.sh`。
- Windows x64 使用 Python 3.13，在仓库目录运行 `py -3.13 -m pip install wxPython==4.2.3 comtypes==1.4.12`，然后运行 `py -3.13 -m hoverling`。

在对应系统上运行 `python -m unittest discover -s tests` 验证共享核心。

### 构建 Linux 包

```bash
python3 tools/package.py linux
```

### 在 Linux 上构建 Windows 便携包

准备 Python 3.10+、LLVM（含 clang、llvm-dlltool、llvm-rc 和 llvm-cvtres）及支持 `ld -m i386pep` 的 GNU binutils。将 LLVM 的 bin 目录加入 PATH，例如 Ubuntu 的 `/usr/lib/llvm-14/bin`。首次构建可用以下命令准备依赖缓存。

```bash
cache_dir="$HOME/.cache/hoverling/windows-x64"
mkdir -p "$cache_dir"
curl -fL https://www.python.org/ftp/python/3.13.12/python-3.13.12-embed-amd64.zip -o "$cache_dir/python-3.13.12-embed-amd64.zip"
python3 -m pip download --dest "$cache_dir" --only-binary=:all: --no-deps --platform win_amd64 --implementation cp --python-version 3.13 --abi cp313 wxPython==4.2.3 comtypes==1.4.12 typing_extensions==4.16.0 numpy==2.5.5
python3 tools/package.py windows --cache "$cache_dir"
```

脚本校验缓存文件的 SHA-256，编译 EXE 启动器，生成自带 Python 的 x64 便携包。后续打包可复用缓存。两种 ZIP 默认输出到 `dist/`，也可以用 `--out` 指定目录。
