#!/usr/bin/env python3
# 开源 CI 用的轻量检查：确认 Python 能编译、源文件是 UTF-8、测试里没有未声明的 Windows 形状路径。
# 不调用格式化工具，也不按行宽重排。现有代码是紧凑写法，新代码沿用所在文件的 4 空格缩进。
import pathlib, py_compile, re, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import utf8io  # noqa: F401
SKIP = {".git", "__pycache__", "memory", "logs", "state", "audit", "kb_inbox", "kb_staging", "kb_prev", "kb_new"}

# `C:/x` 或 `C:\x`：Windows 眼里是绝对路径，POSIX 眼里就是一段普通相对路径（ntpath.isabs 为真，
# posixpath.isabs 为假）。测试拿它当「一个绝对路径」用时，同一行断言在两个系统上测的不是同一件事：
# os.path.join(base, "C:/x") 在 Windows 直接丢掉 base，在 Linux 把 base 和它拼起来。2026-11-04
# 那次 CI 的 ubuntu 格因此红了一格，那条断言本来就一直没测到本意。
# `http://`、`file:///` 这类 URI 的冒号前面是字母，不算盘符。写成源码里的 `C:\\x` 也要抓到，
# 所以只看冒号后面那一个字符是不是分隔符。
WIN_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[/\\]")
FILE_MARK = "# win-path-fixture"
LINE_MARK = "# win-path"

def win_path_fixtures():
    """返回要报的问题列表。测试目录里的盘符路径必须声明过：文件开头整份声明，或者那一行单独声明。"""
    out = []
    for path in sorted((ROOT / "tests").glob("*.py")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeError:
            continue  # 不是 UTF-8 由上面那条检查报，这里不重复
        head = "\n".join(lines[:8])
        hits = [(i, ln) for i, ln in enumerate(lines, 1)
                if WIN_PATH.search(ln) and not ln.lstrip().startswith("#") and LINE_MARK not in ln]
        if hits and FILE_MARK not in head:
            out.append("%s 有 %d 处 Windows 形状的绝对路径字面量（第一处在第 %d 行）：要的是「一个绝对路径」就用 "
                       "tempfile.gettempdir() 现取，两个系统都绝对；确实要 Windows 形状（假进程表、假命令行、"
                       "盘符拒绝用例）时在文件前 8 行写 `%s：<一句原因>`，或在那一行末尾加 `%s`。"
                       % (path.relative_to(ROOT), len(hits), hits[0][0], FILE_MARK, LINE_MARK))
    return out

def main():
    bad = []
    n = 0
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP for part in path.parts):
            continue
        n += 1
        try:
            path.read_text(encoding="utf-8")
        except UnicodeError as e:
            bad.append("%s 不是 UTF-8：%s" % (path.relative_to(ROOT), e))
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as e:
            bad.append("%s 无法编译：%s" % (path.relative_to(ROOT), e.msg))
    bad += win_path_fixtures()
    if bad:
        print("\n".join(bad))
        return 1
    print("lint ok：%d 个 Python 文件可以编译，测试里的 Windows 形状路径都声明过" % n)
    return 0

if __name__ == "__main__":
    sys.exit(main())
