#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
git-contrib-stats: 统计 Git 仓库中每个贡献者的代码行数贡献度与排名。

用法:
    python3 git_contrib_stats.py [仓库路径] [选项]

示例:
    python3 git_contrib_stats.py /path/to/repo
    python3 git_contrib_stats.py /path/to/repo --branch dev --since 2024-01-01
    python3 git_contrib_stats.py /path/to/repo --top 10 --rank-by net --format csv -o result.csv
"""

import argparse
import csv
import json
import subprocess
import sys
from collections import defaultdict

# 二进制文件在 --numstat 中显示为 "-"；作者行以 NUL 字符前缀标记 (由 %x00 生成)
FIELDS_SEP = "\x00"


def run_git(repo, args):
    """执行 git 命令并返回 stdout。"""
    cmd = ["git", "-C", repo] + args
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"[错误] 执行 {cmd!r} 失败: {proc.stderr.strip()}")
    return proc.stdout


def parse_numstat(repo, branch, since, until, pathspec):
    """解析 git log --numstat 输出。

    返回 {author: {commits, files, insertions, deletions}}
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
    in_files = False  # 是否已经进入某个 commit 的文件统计区

    for line in output.splitlines():
        if not line.strip():
            in_files = False
            continue
        if line.startswith(FIELDS_SEP):
            # 新 commit 的作者行
            current_author = line[len(FIELDS_SEP):].strip()
            if current_author:
                stats[current_author]["commits"] += 1
            in_files = False
        elif "\t" in line and current_author:
            # numstat 行: added<TAB>deleted<TAB>path
            parts = line.split("\t", 2)
            if len(parts) == 3:
                added, deleted = parts[0], parts[1]
                if added != "-" and deleted != "-":
                    try:
                        stats[current_author]["insertions"] += int(added)
                        stats[current_author]["deletions"] += int(deleted)
                        stats[current_author]["files"] += 1
                    except ValueError:
                        pass
    return stats


def rank_stats(stats, rank_by):
    """按指定指标排序并计算占比。"""

    def metric(s):
        if rank_by == "insertions":
            return s["insertions"]
        if rank_by == "deletions":
            return s["deletions"]
        if rank_by == "net":
            return s["insertions"] - s["deletions"]
        return s["insertions"] + s["deletions"]  # total

    total = sum(metric(s) for s in stats.values()) or 1
    rows = []
    for rank, (author, s) in enumerate(sorted(stats.items(), key=lambda kv: metric(kv[1]), reverse=True), 1):
        m = metric(s)
        rows.append({
            "rank": rank,
            "author": author,
            "commits": s["commits"],
            "files_changed": s["files"],
            "insertions": s["insertions"],
            "deletions": s["deletions"],
            "net_lines": s["insertions"] - s["deletions"],
            "metric": m,
            "percent": round(m / total * 100, 2),
        })
    return rows


def print_table(rows, rank_by):
    """以对齐表格形式打印到终端。"""
    headers = ["Rank", "Author", "Commits", "Files", "+Lines", "-Lines", "Net", f"{rank_by}(%)"]
    table = [[r["rank"], r["author"], r["commits"], r["files_changed"],
              r["insertions"], r["deletions"], r["net_lines"],
              f"{r['metric']} ({r['percent']}%)"] for r in rows]
    widths = [max(len(str(row[i])) for row in [headers] + table) for i in range(len(headers))]
    line = "  ".join(str(h).ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("-" * len(line))
    for row in table:
        print("  ".join(str(c).ljust(w) for c, w in zip(row, widths)))


def main():
    parser = argparse.ArgumentParser(description="统计 Git 仓库贡献者代码行数贡献度与排名")
    parser.add_argument("repo", nargs="?", default=".", help="Git 仓库路径 (默认当前目录)")
    parser.add_argument("--branch", default="HEAD", help="分支/commit/tag (默认 HEAD)")
    parser.add_argument("--since", help="起始时间, 如 2024-01-01")
    parser.add_argument("--until", help="结束时间, 如 2024-12-31")
    parser.add_argument("--path", help="只统计指定路径/文件, 如 src/")
    parser.add_argument("--top", type=int, default=0, help="只显示前 N 名 (0=全部)")
    parser.add_argument("--rank-by", choices=["insertions", "deletions", "net", "total"],
                        default="insertions", help="排名依据 (默认 insertions, total=增+删)")
    parser.add_argument("--format", choices=["table", "csv", "json"], default="table",
                        help="输出格式 (默认 table)")
    parser.add_argument("-o", "--output", help="输出到文件 (不指定则打印到终端)")
    args = parser.parse_args()

    stats = parse_numstat(args.repo, args.branch, args.since, args.until, args.path)
    if not stats:
        print("未找到任何贡献记录，请检查仓库路径/分支/时间范围。")
        return

    rows = rank_stats(stats, args.rank_by)
    if args.top > 0:
        rows = rows[: args.top]

    if args.format == "csv":
        out = ""
        import io
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        out = buf.getvalue()
    elif args.format == "json":
        out = json.dumps(rows, ensure_ascii=False, indent=2)
    else:
        # table 直接打印
        if args.output:
            import io, contextlib
            buf = io.StringIO()
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
