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
directerior adopt ./outputs my-method exp01 --link --yes
directerior offload my-method exp01 --yes
```

## 工作原理

```
project/                        # 根目录 = .expman.json 所在位置
├── .expman.json                # schema 2 配置 + 防冲突 project_id
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
 methods/.../exp01/3_results ──junction──▶ exp-archive/project--project_id/methods/.../exp01/3_results
        ▲
        └─ 代码继续读写这个路径 — 一切照常
```

Windows 上创建 junction **无需管理员权限**；POSIX 上使用 symlink。

## 快速开始

```bash
cd my-project
uv sync
directerior init --hdd-root D:/exp-archive --threshold-mb 100
directerior new lora-finetune exp01-baseline -d "baseline"

# ... 运行实验，产物写入 3_results/ ...

directerior scan                  # exit 2 = 存在待迁移项
directerior offload lora-finetune exp01-baseline --yes
directerior status
directerior status --verify       # 显式 SHA-256 验证
```

## 自定义层级

两级（`methods` → `experiments`）只是默认值，不是上限 — 在 init 时定义
任意层级：

```bash
directerior init --hdd-root D:/exp-archive --hierarchy datasets,methods,experiments
# datasets/<数据集>/methods/<方法论>/experiments/<实验>/{1_plan,2_code,3_results}
```

之后每条命令按顺序接收每级一个名称：

```bash
directerior new imagenet lora-finetune exp01-baseline
directerior offload imagenet lora-finetune exp01-baseline --yes
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
| `clean [--fix]` | 仅在精确 HDD 目标存在时修复链接；报告未解决链接、孤立数据与回收站（未解决时 exit 2） |
| `migrate-layout [--dry-run] --yes` | 预览变化或转换编号结构 |
| `upgrade-config --yes [--allow-dirty]` | 在全部结果恢复后显式升级至 schema 2 并分配唯一 project ID |
| `history [--json]` | 显示已完成及中断的迁移和路径操作日志 |
| `recover [ID|latest] --yes` | 验证文件系统状态并继续中断的正向操作 |
| `undo [ID|latest] --yes` | 回滚 committed 迁移、`adopt` 或非 purge `rm` |
| `redo [ID|latest] --yes` | 重新应用已 undo 的迁移 |
| `status [--json] [--verify]` | 默认仅统计元数据；`--verify` 添加 SHA-256 验证与 digest |

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

当代理在 Directerior 的固定实验容器之外创建目录时，每一层都应使用数字顺序
前缀和能够说明目的的名称。编号在每个父目录下重新开始，例如
`0_reference/`、`1_analysis/1_functional-states-manuscript-review/` 和
`1_validation/`。目录名称应描述研究活动或交付物的目的，而不是生成它的工具；
避免 `work`、`misc`、`outputs` 等含糊名称。同一请求产生的源规范、交付物和
验证证据应全部放在该请求带编号的目录下。

Directerior 本身只用于实验和实验输出。不要为了管理论文审阅、一次性分析、
报告、演示文稿或文档交付物而创建虚假的方法或 `expNN-*` 目录。

## 严格可逆与可恢复操作

Schema-3 日志保存在项目之外的用户状态目录。`history` 同时显示已完成和中断的操作。

`offload`、`restore`、`rename`、`adopt`、`rm`、`migrate-layout` 会记录每次
文件系统状态转换。若进程中断于数据移动和日志写入之间，
`recover [ID|latest] --yes` 会验证路径、snapshot 与链接目标，只继续此前批准的
正向操作。当前状态若既不匹配记录状态，也不精确匹配其下一状态，则报告冲突，
绝不猜测或覆盖。

`undo` 只接受 committed 记录。迁移支持 `undo`/`redo`；`adopt` 和非 purge
`rm` 支持 `undo`。`rm` 将数据移至
`<hdd_root>/.trash/<project--project_id>/<操作-id>/`。`rm --purge` 永久删除
数据，保留诊断日志，但不可撤销。

旧配置保持可读并继续使用 `<hdd_root>/<项目名>/`。只有全部 offload 结果恢复后，
`upgrade-config --yes` 才会分配 schema-2 project ID。

## 团队使用

提交 `.expman.json`（共享布局与阈值）。每位成员用环境变量指向自己的硬盘，
它会覆盖配置文件：

```bash
set EXPMAN_HDD_ROOT=E:\my-archive      # Windows
export EXPMAN_HDD_ROOT=/mnt/archive    # POSIX
```

Schema-2 项目使用 `<hdd_root>/<项目名>--<project_id>/…`，同名项目也拥有不同的归档命名空间。

## 安全不变式

- `offload`、`restore`、`rename`、`rm`、`adopt`、`migrate-layout`、`recover`、
  `undo`、`redo` **没有 `--yes` 一律失败** — 删除源数据、重新定位或恢复继续
  都必须经用户批准
- offload/restore 按复制 → SHA-256 全树验证 → 删除源数据执行；
  空间不足时在复制前中止
- 普通 `scan` 与 `status` 只读取元数据；仅 `status --verify` 执行 SHA-256 验证
- HDD 目标缺失时 `clean --fix` 不会创建空目录；未解决链接或孤立数据仍返回 exit 2
- **绝不改写源代码** — 会被破坏的引用只报告并拒绝，交由您处理
- **智能体指令文件**（`AGENTS.md`、`CLAUDE.md`、`.claude/` …）不作为移动或删除目标
- 已跟踪文件处于修改状态时，需 `--allow-dirty` 才能重新定位
- `rm` 可通过 HDD 回收站撤销；只有 `--purge` 会销毁数据
- 无静默覆盖 — 目标已存在时一律拒绝
- `restore` / `clean --fix` 只移除链接与空目录，绝不触碰数据
- 孤立的 HDD 数据**只报告，绝不自动删除**

## 许可证

[MIT](LICENSE) © HSoo-Kim
