#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
git-contrib-languages: 统计 Git 仓库中某个提交者的开发语言分布（按文件后缀聚合）。

用法:
    git-contrib-languages <仓库路径> --author <提交者名> [选项]

示例:
    git-contrib-languages /path/to/repo --author Alice
    git-contrib-languages . --author Alice --since 2024-01-01 --rank-by net
    git-contrib-languages . --author Alice --format csv -o alice_langs.csv
"""

import argparse
import csv
import io
import json
import os
import subprocess
import sys
from collections import defaultdict

# 作者行以 NUL 字符前缀标记 (由 git 的 %x00 生成)
FIELDS_SEP = "\x00"

# 无后缀但含义明确的知名文件名，直接映射为可读名称
SPECIAL_NAMES = {
    "makefile": "Makefile",
    "dockerfile": "Dockerfile",
    "jenkinsfile": "Jenkinsfile",
    "cmakelists.txt": "CMake",
    "rakefile": "Ruby",
    "gemfile": "Ruby",
    "pom.xml": "Maven",
    "build.gradle": "Gradle",
    "go.mod": "Go",
    "cargo.toml": "Rust",
}


def run_git(repo, args):
    """执行 git 命令并返回 stdout。"""
    cmd = ["git", "-C", repo] + args
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"[错误] 执行 {cmd!r} 失败: {proc.stderr.strip()}")
    return proc.stdout


def normalize_git_path(path):
    """还原 git 改名标记为新路径。

    git 在 numstat 中对重命名文件输出:
      dir/{old => new}/suffix  (仅目录段变化)
      dir/{old => new}         (文件名变化)
      old => new               (整路径改名)
    """
    if " => " not in path:
        return path
    if "{" in path and "}" in path:
        pre, rest = path.split("{", 1)
        inner, suf = rest.rsplit("}", 1)
        new = inner.split(" => ", 1)[1]
        return pre + new + suf
    return path.split(" => ", 1)[1]


def ext_of(path):
    """从文件路径提取后缀标识（即语言聚合 key）。"""
    path = normalize_git_path(path)
    base = os.path.basename(path).lower()
    if base in SPECIAL_NAMES:
        return SPECIAL_NAMES[base]
    root, ext = os.path.splitext(base)
    if ext and root != "":                   # 常规后缀, 如 .py / .java
        return ext.lstrip(".")
    if base.startswith(".") and root == "":  # 隐藏文件, 如 .gitignore
        return base
    return base                              # 无后缀文件兜底


def parse_author_ext_stats(repo, branch, author, since, until, pathspec):
    """解析 git log --numstat，按后缀聚合指定作者的增删行数。

    返回 {ext: {commits, files, insertions, deletions}}
    """
    git_args = ["log", "--numstat", "--no-merges", "--format=%x00%an", branch]
    if since:
        git_args += ["--since", since]
    if until:
        git_args += ["--until", until]
    if pathspec:
        git_args += ["--", pathspec]

    output = run_git(repo, git_args)

    stats = defaultdict(lambda: {"commits": 0, "files": 0, "insertions": 0, "deletions": 0})
    current_author = None

    for line in output.splitlines():
        if not line.strip():
            # 作者行后有一个空行, 属于正常格式, 不能在此重置作者
            continue
        if line.startswith(FIELDS_SEP):
            current_author = line[len(FIELDS_SEP):].strip()
            continue
        if "\t" in line and current_author and _author_match(current_author, author):
            parts = line.split("\t", 2)
            if len(parts) == 3:
                added, deleted, fpath = parts
                if added != "-" and deleted != "-":
                    try:
                        ins, del_ = int(added), int(deleted)
                    except ValueError:
                        continue
                    ext = ext_of(fpath)
                    stats[ext]["insertions"] += ins
                    stats[ext]["deletions"] += del_
                    stats[ext]["files"] += 1
    return stats


def _author_match(actual, pattern):
    """作者匹配: 精确匹配优先, 否则按子串(大小写不敏感)匹配。"""
    if actual == pattern:
        return True
    return pattern.lower() in actual.lower()


def rank_stats(stats, rank_by):
    def metric(s):
        if rank_by == "deletions":
            return s["deletions"]
        if rank_by == "net":
            return s["insertions"] - s["deletions"]
        if rank_by == "total":
            return s["insertions"] + s["deletions"]
        return s["insertions"]

    total = sum(metric(s) for s in stats.values()) or 1
    rows = []
    for rank, (ext, s) in enumerate(sorted(stats.items(), key=lambda kv: metric(kv[1]), reverse=True), 1):
        m = metric(s)
        rows.append({
            "rank": rank,
            "extension": ext,
            "files_changed": s["files"],
            "insertions": s["insertions"],
            "deletions": s["deletions"],
            "net_lines": s["insertions"] - s["deletions"],
            "metric": m,
            "percent": round(m / total * 100, 2),
        })
    return rows


def print_table(rows, rank_by):
    headers = ["Rank", "Ext", "Files", "+Lines", "-Lines", "Net", f"{rank_by}(%)"]
    table = [[r["rank"], r["extension"], r["files_changed"],
              r["insertions"], r["deletions"], r["net_lines"],
              f"{r['metric']} ({r['percent']}%)"] for r in rows]
    widths = [max(len(str(row[i])) for row in [headers] + table) for i in range(len(headers))]
    line = "  ".join(str(h).ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("-" * len(line))
    for row in table:
        print("  ".join(str(c).ljust(w) for c, w in zip(row, widths)))


def main():
    parser = argparse.ArgumentParser(description="统计某提交者在 Git 仓库中的语言分布（文件后缀分布）")
    parser.add_argument("repo", nargs="?", default=".", help="Git 仓库路径 (默认当前目录)")
    parser.add_argument("--author", required=True, help="提交者名 (支持精确匹配或子串匹配)")
    parser.add_argument("--branch", default="HEAD", help="分支/commit/tag (默认 HEAD)")
    parser.add_argument("--since", help="起始时间, 如 2024-01-01")
    parser.add_argument("--until", help="结束时间, 如 2024-12-31")
    parser.add_argument("--path", help="只统计指定路径, 如 src/")
    parser.add_argument("--top", type=int, default=0, help="只显示前 N 种 (0=全部)")
    parser.add_argument("--rank-by", choices=["insertions", "deletions", "net", "total"],
                        default="insertions", help="排序依据 (默认 insertions)")
    parser.add_argument("--format", choices=["table", "csv", "json"], default="table")
    parser.add_argument("-o", "--output", help="输出到文件")
    args = parser.parse_args()

    stats = parse_author_ext_stats(args.repo, args.branch, args.author,
                                   args.since, args.until, args.path)
    if not stats:
        print(f"未找到提交者 {args.author!r} 的任何提交记录，请检查作者名/分支/时间范围。")
        return

    rows = rank_stats(stats, args.rank_by)
    if args.top > 0:
        rows = rows[: args.top]

    if args.format == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        out = buf.getvalue()
    elif args.format == "json":
        out = json.dumps(rows, ensure_ascii=False, indent=2)
    elif args.output:
        buf = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(buf):
            print_table(rows, args.rank_by)
        out = buf.getvalue()
    else:
        print_table(rows, args.rank_by)
        out = None

    if out is not None:
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(out)
            print(f"结果已写入 {args.output}")
        else:
            print(out)


if __name__ == "__main__":
    main()
