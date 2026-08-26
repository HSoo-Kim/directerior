<div align="center">

# 🗂️ Directerior

**Directory + Interior** — 让您的研究项目目录井然有序、赏心悦目。

*interior : planterior = directory : **directerior***

[English](README.md) | [한국어](README.ko.md) | **中文**

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)
![Dependencies](https://img.shields.io/badge/Dependencies-zero-orange)
[![CI](https://github.com/HSoo-Kim/directerior/actions/workflows/ci.yml/badge.svg)](https://github.com/HSoo-Kim/directerior/actions/workflows/ci.yml)

</div>

---

## 首先是 Agent Skill，其次是安全 CLI

Directerior 是安装给 Claude Code 等智能体的 **Agent Skill**。智能体读取
[SKILL.md](SKILL.md)，设计或映射目录并请求批准，然后调用内置的零依赖
Python CLI 作为安全执行引擎。

| 智能体 | 安装位置 |
|---|---|
| Claude Code（用户级） | `~/.claude/skills/directerior/` |
| Claude Code（项目级） | `<project>/.claude/skills/directerior/` |
| 通用 skill 智能体 | `~/.agents/skills/directerior/` |

通常无需记住 CLI，只需像下面这样告诉 AI。

## 可以这样要求 AI

**开始新研究项目**

> 使用 Directerior 初始化项目。先提出 2~3 个合适的层级让我选择，再创建带编号
> 的 plan/code/results 结构。重新定位数据前必须请求批准。

**只整理现有代码库的产物**

> 我的代码保持原位不动。Directerior 只用来管大体积的输出目录：先显示超过
> 阈值的项，用 `--link` 让硬编码路径继续工作，移动前先问我。

**转换旧 `code/results` 结构**

> 先运行 Directerior `migrate-layout --dry-run`，显示所有变化和 undo 方法。
> 获得批准后才能应用。

**撤销或重做迁移**

> 显示 Directerior history 并验证文件未发生变化。严格 undo 最新迁移前请求批准；
> 我之后要求时再次验证并 redo。

**将大型结果迁移到 HDD**

> 用 Directerior 显示超过 100MB 的结果和 HDD 剩余空间。询问要迁移哪些实验，
> 未批准前不要删除或移动。

研究项目催生实验，实验催生杂乱。结果文件堆在代码旁边，每种方法论的文件夹
形状各不相同，SSD 被 40GB 的 checkpoint 悄悄塞满 — AI 编程智能体只会让
堆积得更快。

**Directerior** 是一个轻量级实验目录管理器：

- 🚧 **只动目录，绝不动代码** — 不重写 import，不修补路径字符串，不碰 `AGENTS.md`；
  会破坏引用的移动**只报告并拒绝**，而不是惄声“修好”
- 📁 **统一布局** — 按方法论、按实验分离 `code/` 与 `results/`
- 🧭 **层级由您定义** — 默认 `methods/experiments`，或任意深度：
  `datasets/methods/experiments`、`phases/trials`……
- ⚖️ **容量监控** — 按阈值（默认 **100MB**）扫描 `results/`，用专用退出码标记待迁移项
- 💾 **HDD 迁移** — 将大体积结果移至副盘，并留下 **junction/symlink**，所有代码路径照常工作
- 🙋 **先审批** — 删除源数据或重新定位数据的命令没有 `--yes` 一律失败；智能体必须先征得您的同意
- 🛡️ **验证传输** — 复制 → SHA-256 全树验证 → 删除源数据；传输前检查可用空间
- ↩️ **可撤销** — `adopt` 与 `rm` 均记入日志；`rm` 将数据移入 HDD 回收站而非删除，
  其余部分由 git 把关
- 🧹 **自我清理** — 修复失效链接、报告孤立数据、清除空目录；**绝不自动删除数据**
- 🪶 **零运行时依赖** — 小型 Python CLI，无数据库，无 DVC

## 推荐用于新项目

Directerior 为**一开始就采用它布局的项目**而设计，因此 `init` 会拒绝已包含真实
源码树的目录（可用 `--allow-existing` 强行继续）。道理很简单：移动目录只需一
毫秒，而让所有 import、硬编码路径、配置文件、notebook 和 shell 脚本跟上这次移动，
则是一个无界限的改代码问题 — 而本工具**故意**选择不改您的代码。

已经有成熟仓库？保持代码原位，只让 Directerior 管产物：

```bash
python scripts/expman.py adopt ./outputs my-method exp01 --link --yes
python scripts/expman.py offload my-method exp01 --yes
```

## 工作原理

```
project/                        # 根目录 = .expman.json 所在位置
├── .expman.json                # { "hdd_root": "D:/exp-archive", "threshold_mb": 100 }
└── methods/
    └── lora-finetune/          # 一种方法论
        └── experiments/
            └── exp01-baseline/ # 一次实验（运行/变体）
                ├── 1_plan/         # 目标、假设、协议、决策
                ├── 2_code/         # 该实验专属脚本与配置
                ├── 3_results/      # 所有产物放这里
                └── manifest.json
```

当 `results/` 超过阈值且您批准迁移后：

```
 SSD（快、小）                              HDD（大、宽裕）
 methods/.../exp01/results  ──junction──▶   exp-archive/project/methods/.../exp01/results
        ▲
        └─ 代码继续读写这个路径 — 一切照常
```

Windows 上创建 junction **无需管理员权限**；POSIX 上使用 symlink。

## 快速开始

```bash
cd my-project
python scripts/expman.py init --hdd-root D:/exp-archive --threshold-mb 100
python scripts/expman.py new lora-finetune exp01-baseline -d "baseline"

# ... 运行实验，产物写入 results/ ...

python scripts/expman.py scan                  # exit 2 = 存在待迁移项
python scripts/expman.py offload lora-finetune exp01-baseline --yes
python scripts/expman.py status
```

## 自定义层级

两级（`methods` → `experiments`）只是默认值，不是上限 — 在 init 时定义
任意层级：

```bash
python scripts/expman.py init --hdd-root D:/exp-archive --hierarchy datasets,methods,experiments
# datasets/<数据集>/methods/<方法论>/experiments/<实验>/{code,results}
```

之后每条命令按顺序接收每级一个名称：

```bash
python scripts/expman.py new imagenet lora-finetune exp01-baseline
python scripts/expman.py offload imagenet lora-finetune exp01-baseline --yes
```

层级保存在 `.expman.json` 中。请在 init 时一次定好 — 数据落地后再改，
需要手动迁移目录。

## 命令

| 命令 | 用途 |
|---|---|
| `init --hdd-root PATH [--threshold-mb N] [--hierarchy a,b,c] [--allow-existing]` | 在项目根目录一次性初始化 |
| `new <名称...> [-d DESC]` | 搭建编号的 plan/code/results 区段 |
| `add <父目录> <slug> [--group N] [--file]` | 创建下一个 `N_slug` 或 `N_a_slug` |
| `scan [--json]` | 列出超过阈值的本地 `results/`（存在则 exit 2） |
| `offload <名称...> --yes` | 将 `results/` 移至 HDD 并链接回原路径 |
| `restore <名称...> --yes` | 验证复制后，经批准删除 HDD 源数据 |
| `rename <旧名称...> --to <新名称...> --yes` | 同步重命名本地 leaf 与 HDD 镜像 |
| `rm <名称...> --yes [--purge]` | 将本地 leaf 与 HDD 副本移入 HDD 回收站；`--purge` 永久删除 |
| `adopt <path> <名称...> [--as NAME] [--link] [--allow-breaking-refs] --yes` | 收编位置不对的产物；`--link` 保持原路径可用 |
| `clean [--fix]` | 清除 HDD 空目录、修复失效链接、报告孤立数据与回收站 |
| `migrate-layout [--dry-run] --yes` | 预览变化或转换编号结构 |
| `history [--json]` | 显示可逆操作记录（迁移、`adopt`、`rm`） |
| `undo [ID|latest] --yes` | 严格验证后回滚迁移、`adopt` 或 `rm` |
| `redo [ID|latest] --yes` | 重新应用已 undo 的迁移 |
| `status [--json]` | 每个实验：字节数与 local/HDD 位置 |

所有重新定位数据的命令还接受 `--allow-dirty`（见下文）。

## 意外输出路径

工具偏爱硬编码路径（`./outputs/`、`./wandb/`、`~/runs/`）。当产物落在布局之外时，
[SKILL.md](SKILL.md) 中的智能体契约要求**必须询问您** — 给出编号选项（收编、
收编+链接回原路、放入 `_shared` 方法论、保持原样、或手动输入目标路径），
而不是擅自移动。

对付固执的工具用 `adopt --link`：产物移入 `results/`，原路径留下 junction，
工具照常运行。

## 引用拦截器

不带 `--link` 的 `adopt` 会先在项目中搜索引用该路径的文本 — 对代码区段还会搜索
`import <模块>`。一旦命中就中止移动，并列出到底什么会坏：

```text
ERROR: moving /home/me/proj/outputs would break 2 reference(s):
  train.py:14: OUT = "outputs/checkpoints"
  AGENTS.md:52: outputs/ holds every checkpoint
  directerior does not rewrite code, configs, or docs.
  Use --link to keep the original path working, fix the references yourself,
  or pass --allow-breaking-refs to move anyway.
```

只报告，不修复。自动改写 import 和路径字符串是一种失败无声的 codemod — 错误路径
不会报错，只会静静地产出空结果 — 所以这个决定留给您。

## 以 git 作为事务边界

在 git 仓库中，只要**已跟踪**文件处于修改状态，重新定位类命令就拒绝执行，
以保证 `git reset --hard` 始终是有效的退路。未跟踪文件（结果、checkpoint）不会
阻挡，因为 git 本来就无法恢复它们；那部分由操作日志负责。`--allow-dirty` 可覆盖。

## 新项目与现有项目

新项目自动创建 `1_plan/`、`2_code/`、`3_results/`。现有 Directerior
项目可运行 `migrate-layout --yes`。任意现有代码库按设计不在支持范围内 —
参见[推荐用于新项目](#推荐用于新项目)。

默认仅用数字：`1_baseline`、`2_training`。同一第 1 阶段出现并行分支时才
扩展为 `1_a_baseline`、`1_b_augmented`。`add` 自动计算下一个前缀。

## 严格可逆操作

日志保存在项目之外的用户状态目录，因此恢复后的项目内不会残留记账文件。
同一个 `history` 下共存两类记录：

| 类别 | 命令 | 验证 | 回滚 |
|---|---|---|---|
| migration | `migrate-layout` | SHA-256 内容全量 | `undo` + `redo` |
| path operation | `adopt`、`rm` | 路径/大小结构 | `undo`（重新执行命令即可重做） |

`rm` 不再删除，而是将实验及其 HDD 副本移至
`<hdd_root>/.trash/<项目>/<操作-id>/`，`undo` 连同 offload 链接一并还原。
真正销毁数据的只有 `--purge`。

undo/redo 前会验证 `.expman.json`
原始字节、每个相关文件的路径/大小/SHA-256、空目录、HDD 位置和 junction
状态。任何内容变化都会在移动前拒绝。成功 undo 会恢复原名称、文件字节、
配置格式、HDD 路径与链接；仅外部日志保留，以便 redo。

schema v2 日志同时也是未来 version graph 的 edge：

```text
parent_id -> operation_id
before_fingerprint -> after_fingerprint
operation_type = migrate_layout
```

fingerprint 描述项目状态而非命令文字，因此未来 rename、offload 等操作可在前一
操作结果与下一操作输入相同时连接到同一 graph。旧 schema v1 日志仍可读取；
Directerior 会在加载时推导缺失的 fingerprint。

## 团队使用

提交 `.expman.json`（共享布局与阈值）。每位成员用环境变量指向自己的硬盘，
它会覆盖配置文件：

```bash
set EXPMAN_HDD_ROOT=E:\my-archive      # Windows
export EXPMAN_HDD_ROOT=/mnt/archive    # POSIX
```

迁移数据存放于 `<hdd_root>/<项目名>/…`，一块归档盘可服务多个项目而互不冲突。

## 安全不变式

- `offload`、`restore`、`rename`、`rm`、`adopt`、`migrate-layout`、`undo`、
  `redo` **没有 `--yes`
  一律失败** — 删除源数据或重新定位必须经用户批准
- offload/restore 按复制 → SHA-256 全树验证 → 删除源数据执行；
  空间不足时在复制前中止
- **绝不改写源代码** — 会被破坏的引用只报告并拒绝，交由您处理
- **智能体指令文件**（`AGENTS.md`、`CLAUDE.md`、`.claude/` …）不作为移动或删除目标
- 已跟踪文件处于修改状态时，需 `--allow-dirty` 才能重新定位
- `rm` 可通过 HDD 回收站撤销；只有 `--purge` 会销毁数据
- 无静默覆盖 — 目标已存在时一律拒绝
- `restore` / `clean --fix` 只移除链接与空目录，绝不触碰数据
- 孤立的 HDD 数据**只报告，绝不自动删除**

## 许可证

[MIT](LICENSE) © HSoo-Kim
