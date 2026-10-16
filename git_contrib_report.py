#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
git-contrib-report: 生成 Git 仓库贡献度交互式 HTML 报告。

柱状图 + 表格展示每个贡献者的代码量，点击作者名弹出该人的语言分布饼图。

用法:
    git-contrib-report /path/to/repo
    git-contrib-report /path/to/repo --branch dev --since 2024-01-01
    git-contrib-report /path/to/repo -o report.html --rank-by net
"""

import argparse
import json
import os
import subprocess
import sys
import html
from collections import defaultdict
from datetime import datetime

FIELDS_SEP = "\x00"

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
    cmd = ["git", "-C", repo] + args
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"[错误] 执行 {cmd!r} 失败: {proc.stderr.strip()}")
    return proc.stdout


def normalize_git_path(path):
    """还原 git 改名标记为新路径。"""
    if " => " not in path:
        return path
    if "{" in path and "}" in path:
        pre, rest = path.split("{", 1)
        inner, suf = rest.rsplit("}", 1)
        new = inner.split(" => ", 1)[1]
        return pre + new + suf
    return path.split(" => ", 1)[1]


def ext_of(path):
    path = normalize_git_path(path)
    base = os.path.basename(path).lower()
    if base in SPECIAL_NAMES:
        return SPECIAL_NAMES[base]
    root, ext = os.path.splitext(base)
    if ext and root != "":
        return ext.lstrip(".")
    if base.startswith(".") and root == "":
        return base
    return base


def collect(repo, branch, since, until, pathspec):
    """一次遍历, 同时收集: 作者总体统计 + 作者x后缀统计。"""
    git_args = ["log", "--numstat", "--no-merges", "--format=%x00%an", branch]
    if since:
        git_args += ["--since", since]
    if until:
        git_args += ["--until", until]
    if pathspec:
        git_args += ["--", pathspec]

    authors = defaultdict(lambda: {"commits": 0, "files": 0,
                                    "insertions": 0, "deletions": 0})
    exts = defaultdict(lambda: defaultdict(lambda: {"files": 0,
                                                    "insertions": 0, "deletions": 0}))
    current_author = None

    for line in run_git(repo, git_args).splitlines():
        if not line.strip():
            continue  # 作者行后的空行, 属于正常格式
        if line.startswith(FIELDS_SEP):
            current_author = line[len(FIELDS_SEP):].strip()
            if current_author:
                authors[current_author]["commits"] += 1
            continue
        if "\t" in line and current_author:
            parts = line.split("\t", 2)
            if len(parts) == 3:
                added, deleted, fpath = parts
                if added == "-" or deleted == "-":
                    continue
                try:
                    ins, dele = int(added), int(deleted)
                except ValueError:
                    continue
                a = authors[current_author]
                a["insertions"] += ins
                a["deletions"] += dele
                a["files"] += 1
                ext = ext_of(fpath)
                e = exts[current_author][ext]
                e["insertions"] += ins
                e["deletions"] += dele
                e["files"] += 1
    return authors, exts


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Git 贡献度报告 - __REPO__</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #f5f6fa; color: #2f3542; padding: 32px; }
  .card { background: #fff; border-radius: 12px; padding: 24px;
          box-shadow: 0 2px 12px rgba(0,0,0,.08); margin-bottom: 24px; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  .sub { color: #747d8c; font-size: 13px; margin-bottom: 20px; }
  h2 { font-size: 16px; margin-bottom: 16px; }
  .bar-row { display: flex; align-items: center; margin: 8px 0; }
  .bar-label { width: 160px; text-align: right; padding-right: 12px;
               font-size: 13px; white-space: nowrap; overflow: hidden;
               text-overflow: ellipsis; cursor: pointer; color: #273c75; }
  .bar-label:hover { text-decoration: underline; }
  .bar-track { flex: 1; background: #eef0f4; border-radius: 4px; height: 22px; }
  .bar-fill { height: 100%; border-radius: 4px; min-width: 2px;
              background: linear-gradient(90deg,#4b7bec,#3867d6); position: relative; }
  .bar-value { width: 130px; padding-left: 10px; font-size: 13px; color: #57606f; }
  table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
  th, td { padding: 9px 12px; text-align: right; border-bottom: 1px solid #ecf0f1; }
  th:nth-child(2), td:nth-child(2) { text-align: left; }
  th { color: #57606f; font-weight: 600; background: #fbfbfd; }
  td.author { color: #273c75; font-weight: 500; cursor: pointer; }
  td.author:hover { text-decoration: underline; }
  tr:hover td { background: #f8faff; }
  .pill { display:inline-block; background:#eef3ff; color:#273c75;
          border-radius:10px; padding:1px 8px; font-size:12px; }
  .overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.45);
             z-index: 10; align-items: center; justify-content: center; }
  .overlay.open { display: flex; }
  .modal { background: #fff; border-radius: 14px; padding: 28px 32px; width: 560px;
           max-width: 92vw; max-height: 86vh; overflow: auto;
           box-shadow: 0 12px 40px rgba(0,0,0,.25); }
  .modal h3 { font-size: 18px; margin-bottom: 4px; }
  .modal .msub { color:#747d8c; font-size:12.5px; margin-bottom:18px; }
  .pie-wrap { display: flex; align-items: center; gap: 24px; flex-wrap: wrap; }
  .legend { font-size: 13px; }
  .legend div { margin: 4px 0; }
  .dot { display:inline-block; width:10px; height:10px; border-radius:50%;
         margin-right:6px; }
  .close { float: right; cursor: pointer; border: none; background: none;
           font-size: 20px; color: #747d8c; }
  .close:hover { color: #2f3542; }
</style>
</head>
<body>
<h1>Git 贡献度报告 <span class="pill">__REPO__</span></h1>
<div class="sub">排名依据: __RANKBY__ &nbsp;|&nbsp; 分支: __BRANCH__ &nbsp;|&nbsp; 生成时间: __TIME__</div>

<div class="card">
  <h2>代码量贡献柱状图 (点击姓名查看语言分布)</h2>
  <div id="bars"></div>
</div>

<div class="card">
  <h2>贡献者明细 (点击姓名查看语言分布)</h2>
  <table>
    <thead><tr>
      <th>Rank</th><th>Author</th><th>Commits</th><th>Files</th>
      <th>+Lines</th><th>-Lines</th><th>Net</th><th>占比</th>
    </tr></thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

<div class="overlay" id="overlay">
  <div class="modal">
    <button class="close" onclick="closeModal()">&times;</button>
    <h3 id="m-title"></h3>
    <div class="msub" id="m-sub"></div>
    <div class="pie-wrap">
      <svg id="pie" width="240" height="240" viewBox="0 0 240 240"></svg>
      <div class="legend" id="legend"></div>
    </div>
  </div>
</div>

<script>
const DATA = __DATA__;

const COLORS = ["#3867d6","#26de81","#fd9644","#fc5c65","#a55eea","#2bcbba",
  "#f7b731","#eb3b5a","#0fb9b1","#8854d0","#4b6584","#fa8231","#20bf6b"];

const fmt = n => n.toLocaleString('en-US');

function render() {
  const max = Math.max(...DATA.rows.map(r => r.metric), 1);
  document.getElementById('bars').innerHTML = DATA.rows.map(r => `
    <div class="bar-row">
      <div class="bar-label" title="${r.author}" onclick="showPie('${esc(r.author)}')">${esc(r.author)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(r.metric/max*100).toFixed(1)}%"></div></div>
      <div class="bar-value">${fmt(r.metric)} (${r.percent}%)</div>
    </div>`).join('');

  document.getElementById('tbody').innerHTML = DATA.rows.map(r => `
    <tr>
      <td>${r.rank}</td>
      <td class="author" onclick="showPie('${esc(r.author)}')">${esc(r.author)}</td>
      <td>${r.commits}</td><td>${r.files}</td>
      <td>${fmt(r.insertions)}</td><td>${fmt(r.deletions)}</td>
      <td>${fmt(r.net)}</td><td>${r.percent}%</td>
    </tr>`).join('');
}

function esc(s) { return s.replace(/'/g,"\\\\'").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

function closeModal() { document.getElementById('overlay').classList.remove('open'); }
document.getElementById('overlay').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeModal();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

function showPie(author) {
  const rows = DATA.langs[author] || [];
  const total = rows.reduce((s, r) => s + r.metric, 0) || 1;
  document.getElementById('m-title').textContent = author + ' — 语言分布';
  document.getElementById('m-sub').textContent =
    `按 ${DATA.rankBy} 行数统计, 共 ${fmt(total)} 行 / ${DATA.langsMeta[author] || 0} 次提交`;

  // SVG 饼图 (扇形路径)
  const cx = 120, cy = 120, r = 100, ir = 58;
  let angle = -Math.PI / 2, paths = '';
  rows.forEach((row, i) => {
    const frac = row.metric / total;
    const a2 = angle + frac * Math.PI * 2;
    const x1 = cx + r * Math.cos(angle), y1 = cy + r * Math.sin(angle);
    const x2 = cx + r * Math.cos(a2),     y2 = cy + r * Math.sin(a2);
    const xi2 = cx + ir * Math.cos(a2),   yi2 = cy + ir * Math.sin(a2);
    const xi1 = cx + ir * Math.cos(angle),yi1 = cy + ir * Math.sin(angle);
    const large = frac > 0.5 ? 1 : 0;
    if (frac > 0.999) {  // 满圆特殊处理
      paths += `<circle cx="${cx}" cy="${cy}" r="${(r+ir)/2}" fill="none"
                 stroke="${COLORS[i%COLORS.length]}" stroke-width="${r-ir}"/>`;
    } else {
      paths += `<path d="M${x1},${y1} A${r},${r} 0 ${large} 1 ${x2},${y2}
                 L${xi2},${yi2} A${ir},${ir} 0 ${large} 0 ${xi1},${yi1} Z"
                 fill="${COLORS[i%COLORS.length]}"/>`;
    }
    angle = a2;
  });
  document.getElementById('pie').innerHTML = paths;

  document.getElementById('legend').innerHTML = rows.map((row, i) => `
    <div><span class="dot" style="background:${COLORS[i%COLORS.length]}"></span>
    <b>${esc(row.ext)}</b> — ${fmt(row.metric)} 行 (${(row.metric/total*100).toFixed(1)}%)</div>
  `).join('');

  document.getElementById('overlay').classList.add('open');
}

render();
</script>
</body>
</html>
"""


def build_report(authors, exts, repo, branch, rank_by):
    def metric_of(ins, dele):
        if rank_by == "deletions":
            return dele
        if rank_by == "net":
            return ins - dele
        if rank_by == "total":
            return ins + dele
        return ins

    rows = []
    for a, s in authors.items():
        m = metric_of(s["insertions"], s["deletions"])
        rows.append({"author": a, "commits": s["commits"], "files": s["files"],
                     "insertions": s["insertions"], "deletions": s["deletions"],
                     "net": s["insertions"] - s["deletions"], "metric": m})
    rows.sort(key=lambda r: r["metric"], reverse=True)
    total = sum(r["metric"] for r in rows) or 1
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["percent"] = round(r["metric"] / total * 100, 2)

    langs, langs_meta = {}, {}
    for a, ext_map in exts.items():
        items = []
        for ext, s in ext_map.items():
            m = metric_of(s["insertions"], s["deletions"])
            if m > 0 or s["insertions"] + s["deletions"] > 0:
                items.append({"ext": ext, "files": s["files"],
                              "insertions": s["insertions"], "deletions": s["deletions"],
                              "metric": m})
        items.sort(key=lambda x: x["metric"], reverse=True)
        langs[a] = items[:15]  # 饼图最多展示 15 类, 避免过碎
        langs_meta[a] = authors[a]["commits"]

    return {"rows": rows, "langs": langs, "langsMeta": langs_meta,
            "rankBy": rank_by}


def main():
    parser = argparse.ArgumentParser(description="生成 Git 仓库贡献度交互式 HTML 报告")
    parser.add_argument("repo", nargs="?", default=".", help="Git 仓库路径 (默认当前目录)")
    parser.add_argument("--branch", default="HEAD", help="分支/commit/tag (默认 HEAD)")
    parser.add_argument("--since", help="起始时间, 如 2024-01-01")
    parser.add_argument("--until", help="结束时间, 如 2024-12-31")
    parser.add_argument("--path", help="只统计指定路径, 如 src/")
    parser.add_argument("--rank-by", choices=["insertions", "deletions", "net", "total"],
                        default="insertions", help="排名依据 (默认 insertions)")
    parser.add_argument("-o", "--output", help="输出 HTML 文件路径")
    args = parser.parse_args()

    repo = os.path.abspath(args.repo)
    authors, exts = collect(repo, args.branch, args.since, args.until, args.path)
    if not authors:
        print("未找到任何贡献记录，请检查仓库路径/分支/时间范围。")
        return

    data = build_report(authors, exts, os.path.basename(repo), args.branch, args.rank_by)

    rank_names = {"insertions": "新增行数", "deletions": "删除行数",
                  "net": "净增行数", "total": "增删总行数"}
    page = HTML_TEMPLATE.replace("__REPO__", html.escape(os.path.basename(repo))) \
                        .replace("__RANKBY__", rank_names[args.rank_by]) \
                        .replace("__BRANCH__", html.escape(args.branch)) \
                        .replace("__TIME__", datetime.now().strftime("%Y-%m-%d %H:%M")) \
                        .replace("__DATA__", json.dumps(data, ensure_ascii=False))

    output = args.output or f"contrib_report_{os.path.basename(repo)}.html"
    with open(output, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"报告已生成: {output}")
    print(f"共 {len(data['rows'])} 位贡献者, 排名依据: {rank_names[args.rank_by]}")


if __name__ == "__main__":
    main()
