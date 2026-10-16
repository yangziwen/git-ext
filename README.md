# git-ext

Git 扩展命令集：一组用 Python 实现的 Git 代码贡献度分析工具。

## 包含的工具

| 文件 | 命令 | 功能 |
|------|------|------|
| `git_contrib_stats.py` | `git contrib-stats` | 按贡献者统计代码增删行数与排名 |
| `git_contrib_languages.py` | `git contrib-languages` | 统计指定贡献者的语言分布（文件后缀分布） |
| `git_contrib_report.py` | `git contrib-report` | 生成交互式 HTML 贡献度报告（柱状图 + 饼图） |

## 安装

### 原理

Git 支持自定义子命令：任何放在 `PATH` 环境变量目录中、命名为 `git-<xxx>` 的**可执行文件**，都可以通过 `git <xxx>`（空格分隔）直接调用，效果与执行 `git-<xxx>` 完全相同。

### 步骤

把本仓库中的三个文件（去掉 `.py` 后缀，重命名为带连字符的命令名）复制到 PATH 中的任意目录并赋予执行权限即可。推荐放在 `/usr/local/bin`（macOS/Linux 上通常已在 PATH 中，且一般无需 sudo）：

```bash
git clone git@github.com:yangziwen/git-ext.git
cd git-ext

cp git_contrib_stats.py      /usr/local/bin/git-contrib-stats
cp git_contrib_languages.py  /usr/local/bin/git-contrib-languages
cp git_contrib_report.py     /usr/local/bin/git-contrib-report
chmod +x /usr/local/bin/git-contrib-*
```

安装完成后，在任意目录都可以使用：

```bash
git-contrib-stats /path/to/repo          # 直接调用
git contrib-stats /path/to/repo          # 通过 git 子命令方式调用，二者等价
```

> 注意：`git contrib-stats --help` 会被 git 拦截转去查 man 手册导致报错，查看帮助请用 `git-contrib-stats --help` 或 `git contrib-stats -h`。

依赖：仅需要 Python 3.6+ 和 git，无第三方包。

## 功能与用法

三个工具均基于 `git log --numstat` 解析，自动跳过 merge 提交和二进制文件，并正确处理文件重命名路径。统计口径为 **历史提交的增量行数累计**（新增/删除分别累计），而非最新代码的逐行归属（那是 `git blame` 的语义）。

### 1. git contrib-stats — 贡献者排名

统计每个贡献者的提交数、改动文件数、增删行数，并按贡献度排名，支持表格/CSV/JSON 输出。

```bash
git contrib-stats /path/to/repo
git contrib-stats /path/to/repo --branch dev --since 2024-01-01
git contrib-stats /path/to/repo --rank-by net --top 10 --format csv -o result.csv
```

| 选项 | 说明 |
|------|------|
| `repo` | 仓库路径，默认当前目录 |
| `--branch` | 分支 / commit / tag，默认 HEAD |
| `--since` / `--until` | 时间范围，如 `2024-01-01` |
| `--path` | 只统计指定路径或文件，如 `src/` |
| `--top N` | 只显示前 N 名 |
| `--rank-by` | 排名依据：`insertions`（默认）/ `deletions` / `net`（净增）/ `total`（增删总和） |
| `--format` | 输出格式：`table`（默认）/ `csv` / `json` |
| `-o FILE` | 输出到文件 |

输出示例：

```
Rank  Author  Commits  Files  +Lines  -Lines  Net  insertions(%)
----------------------------------------------------------------
1     Bob     1        2      3       0       3    3 (37.5%)
2     Alice   1        1      3       0       3    3 (37.5%)
```

### 2. git contrib-languages — 指定贡献者的语言分布

统计某个提交者的代码量按文件后缀（语言）的分布。作者名支持精确匹配或子串匹配（大小写不敏感）；`Makefile`、`Dockerfile`、`pom.xml`（归为 Maven）、`build.gradle`（Gradle）等知名无后缀/特殊文件会映射为可读名称。

```bash
git contrib-languages /path/to/repo --author Alice
git contrib-languages . --author Alice --since 2024-01-01 --rank-by net
git contrib-languages . --author Alice --format json
```

选项与 contrib-stats 基本一致，另有：

| 选项 | 说明 |
|------|------|
| `--author` | **必填**，提交者名 |
| `--top N` | 只显示前 N 种后缀 |

输出示例：

```
Rank  Ext       Files  +Lines  -Lines  Net  insertions(%)
---------------------------------------------------------
1     py        2      3       0       3    3 (60.0%)
2     Makefile  1      1       0       1    1 (20.0%)
```

### 3. git contrib-report — 交互式 HTML 报告

生成一个**单文件** HTML 报告（无任何外部依赖，双击即可离线打开）：

- 柱状图展示每位贡献者的代码量与占比
- 明细表格：Rank / Author / Commits / Files / +Lines / -Lines / Net / 占比
- 点击柱状图或表格中的任意作者名，弹出该人的语言分布环形饼图（含图例）；按 Esc 或点击遮罩关闭

```bash
git contrib-report /path/to/repo
git contrib-report /path/to/repo --since 2026-01-01 --authors "alice,bob" -o report.html
git contrib-report /path/to/repo -o report.html --rank-by net
```

| 选项 | 说明 |
|------|------|
| `-o FILE` | 输出 HTML 路径，默认 `contrib_report_<仓库名>.html` |
| `--rank-by` | 排名依据，柱状图/表格/饼图同步联动 |
| `--authors` | 只统计指定作者（白名单），逗号分隔，如 `"yangziwen,zhangyoujie"`；支持子串/大小写不敏感匹配，非白名单作者的提交完全排除 |
| `--branch` / `--since` / `--until` / `--path` | 同上 |

> 报告数据在生成时静态嵌入，仓库有新提交后需重新执行刷新。

## 口径说明

- 统计的是每个 commit 的增删行数累计：早期写入、后来被删除的代码仍计入其作者名下；同一段代码被多次重写会重复累计。
- 想了解"最新版本里每行代码是谁写的"，请使用 `git blame`（语义不同，二者互补）。
