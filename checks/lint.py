#!/usr/bin/env python3
# 开源 CI 用的轻量检查：确认 Python 能编译、源文件是 UTF-8、测试里没有未声明的 Windows 形状路径。
# 不调用格式化工具，也不按行宽重排。现有代码是紧凑写法，新代码沿用所在文件的 4 空格缩进。
#
# 2026-11-09 按 poteto/plugins 的 pstack（Lauren Tan 开源 Agent Harness）的
# `principle-encode-lessons-in-structure` 补了两条「结构防线」：把项目里踩过两次的坑编码成
# lint 硬规则，而不是往文档里加警告——文档能被跳过且不报错，lint 当场拦截。
# 每条规则都带真实踩坑出处，并且 `python checks/lint.py --selftest` 会用坏样例证明规则真会红
# （对应 pstack 的「新检查必须在真实历史错误上先挂一次」）。
import pathlib, py_compile, re, sys, tempfile

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
# 规则 A：测试里引用 gitignored 实例生产配置的允许例外声明（文件前 8 行）。
GITIGNORED_MARK = "# gitignored-config-fixture"
# 规则 B：Node 入口判定只认 pathToFileURL 那一种写法。
NODE_ENTRY_BAD = re.compile(r'new URL\(import\.meta\.url\)\.pathname\s*===')


def win_path_fixtures():
    """返回要报的问题列表。测试目录里的盘符路径必须声明过：文件开头整份声明，或者那一行单独声明。"""
    return _win_path_in(ROOT / "tests")


def _win_path_in(tests_dir):
    out = []
    for path in sorted(tests_dir.glob("*.py")):
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


# ── 规则 A：测试不得硬编码引用 gitignored 的实例生产配置（2026-11-09 踩坑） ──
def prod_config_in_tests():
    return _prod_config_in(ROOT / "tests")


def _prod_config_in(tests_dir):
    """tests/*.py 里若出现 `agents/<名字>.json`（example / config.schema 之外），那就是在依赖
    gitignored 的实例生产配置，CI checkout 里没有那个文件。
    出处：test_juchang 的 e2e 直接 json.load(agents/mimi.json)，CI ubuntu 上整格崩（mimi.json 被
    .gitignore 忽略，不在 checkout）。要测真实配置的形态就本机 os.path.isfile 守卫 + 用仓库内
    等价内联蓝本，或在文件前 8 行写声明真的需要它。"""
    rx = re.compile(r"['\"]agents/(?!example|config\.schema)[a-z0-9_]+\.json['\"]")
    out = []
    for path in sorted(tests_dir.glob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        head = "\n".join(text.splitlines()[:8])
        m = rx.search(text)
        if m and GITIGNORED_MARK not in head:
            out.append("%s 第 %d 行引用了 gitignored 实例生产配置 `agents/%s`，CI checkout 没有它。"
                       "改用仓库内联配置蓝本（本机再用 os.path.isfile 守卫核对真实配置的形态），"
                       "或文件前 8 行写 `%s`。"
                       % (path.relative_to(tests_dir), text[:m.start()].count("\n") + 1, m.group(0)[8:], GITIGNORED_MARK))
    return out


# ── 规则 B：Node 脚本入口判定只用 pathToFileURL 一种写法 ──
def node_entry_detection():
    return _node_entry_in(ROOT / "skills")


def _node_entry_in(skills_dir):
    """skills/**/scripts/*.mjs 的入口判定不得把 argv[1] 手拼成路径再与 URL pathname 比。
    2026-11-08 踩坑：verify-matrix-receipts.mjs 原版 `replaceAll("\\", "/").replace(/^([A-Za-z]):/, "/$1:")`
    再与 `new URL(import.meta.url).pathname` 比较；CI 的 TEMP 是 8.3 短路径（RUNNER~1，含 `~`），
    `~` 在 URL pathname 里被百分号编码成 %7E 而手拼路径不编码 → 永不相等 → 入口静默不执行（exit 0 无输出）。
    标准写法：`pathToFileURL(process.argv[1]).href === import.meta.url`。"""
    out = []
    for path in sorted(skills_dir.rglob("scripts/*.mjs")):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        m = NODE_ENTRY_BAD.search(text)
        if m:
            out.append("%s 第 %d 行用手拼路径比较 URL pathname（含 `~`/非 ASCII 的路径会被 %%7E/%%XX 编码而永不相等，"
                       "入口静默不执行）。改用 `pathToFileURL(process.argv[1]).href === import.meta.url`。"
                       % (path.relative_to(skills_dir), text[:m.start()].count("\n") + 1))
    return out


def _selftest():
    """`python checks/lint.py --selftest`：用坏样例证明每条规则真能红（pstack 的「新检查必须先挂过
    真实错误」的落地），再用好样例证明不误报。坏/好样例放不同子目录，避免互相干扰。"""
    problems = []
    with tempfile.TemporaryDirectory(prefix="lint_selftest_") as td:
        root = pathlib.Path(td)
        # ── 规则 A ──
        t_bad = root / "tests_bad"; t_bad.mkdir()
        (t_bad / "bad.py").write_text("import json\ncfg = json.load(open('agents/mimi.json', encoding='utf-8-sig'))\n", encoding="utf-8")
        if not _prod_config_in(t_bad):
            problems.append("规则 A 的坏样例（引用 agents/mimi.json）没被抓到")
        t_good = root / "tests_good"; t_good.mkdir()
        (t_good / "good.py").write_text("import os\nreal = os.path.join('agents', 'mimi.json')\n"
                                        "if os.path.isfile(real):\n    pass\n", encoding="utf-8")
        if _prod_config_in(t_good):
            problems.append("规则 A 把不违反（os.path.isfile 守卫）的样例误报了")
        # ── 规则 B ──
        s_bad = root / "skills_bad"; (s_bad / "x" / "scripts").mkdir(parents=True)
        (s_bad / "x" / "scripts" / "bad.mjs").write_text(
            "const invokedPath = process.argv[1]?.replaceAll('\\\\', '/').replace(/^([A-Za-z]):/, '/$1:');\n"
            "if (invokedPath && new URL(import.meta.url).pathname === invokedPath) {}\n", encoding="utf-8")
        if not _node_entry_in(s_bad):
            problems.append("规则 B 的坏样例（手拼 URL pathname）没被抓到")
        s_good = root / "skills_good"; (s_good / "x" / "scripts").mkdir(parents=True)
        (s_good / "x" / "scripts" / "good.mjs").write_text(
            "const invokedPath = process.argv[1] ? pathToFileURL(process.argv[1]).href : '';\n"
            "if (invokedPath && invokedPath === import.meta.url) {}\n", encoding="utf-8")
        if _node_entry_in(s_good):
            problems.append("规则 B 把 pathToFileURL 写法误报了")
    return problems


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
    bad += prod_config_in_tests()
    bad += node_entry_detection()
    if "--selftest" in sys.argv[1:]:
        bad += _selftest()
    if bad:
        print("\n".join(bad))
        return 1
    suffix = "（含自检）" if "--selftest" in sys.argv[1:] else ""
    print("lint ok：%d 个 Python 文件可以编译，测试里的 Windows 形状路径都声明过，gitignored 配置与"
          " Node 入口判定都合规%s" % (n, suffix))
    return 0


if __name__ == "__main__":
    sys.exit(main())