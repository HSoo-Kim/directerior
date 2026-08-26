<div align="center">

# 🗂️ Directerior

**Directory + Interior** — keep your research project's directories beautifully arranged.

*interior : planterior = directory : **directerior***

**English** | [한국어](README.ko.md) | [中文](README.zh.md)

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)
![Dependencies](https://img.shields.io/badge/Dependencies-zero-orange)
[![CI](https://github.com/HSoo-Kim/directerior/actions/workflows/ci.yml/badge.svg)](https://github.com/HSoo-Kim/directerior/actions/workflows/ci.yml)

</div>

---

## Agent Skill first, CLI underneath

Directerior is an **Agent Skill** you give to Claude Code or another
skill-aware coding agent. The agent reads [SKILL.md](SKILL.md), designs or
maps your directory structure, asks before moving/deleting data, then drives
the bundled zero-dependency Python CLI as its safety engine.

| Agent | Install this repository at |
|---|---|
| Claude Code (user-wide) | `~/.claude/skills/directerior/` |
| Claude Code (project) | `<project>/.claude/skills/directerior/` |
| Generic skill-aware agents | `~/.agents/skills/directerior/` |

You normally talk to your agent; you do not need to memorize CLI commands.

## What to ask your AI

**Start a new research project**

> Use the Directerior skill to initialize this project. Propose 2-3 suitable
> hierarchies first, ask me to choose one, then create the numbered
> plan/code/results structure. Ask before any data relocation.

**Tame the outputs of an existing codebase**

> My code is staying exactly where it is. Use Directerior only for the big
> output directories: show me what is over the threshold, use `--link` so my
> hardcoded paths keep working, and ask before moving anything.

**Convert an existing `code/results` Directerior layout**

> Run Directerior migration as a dry run first. Show every path that will
> change and tell me how to undo it. Ask for approval before applying it.

**Undo or redo a migration**

> Show Directerior migration history. Verify that files have not changed,
> then ask before strictly undoing the latest migration. If I later ask,
> verify again and redo the same operation.

**Offload large results**

> Scan with Directerior. Show experiments over 100MB and available HDD space.
> Ask which ones I want to offload; do not delete or relocate anything before
> I approve.

Research projects breed experiments, and experiments breed clutter. Results
pile up next to code, every methodology invents its own folder shape, and
your SSD quietly fills with 40GB of checkpoints — AI coding agents only make
the pile grow faster.

**Directerior** is a lightweight experiment directory manager:

- 🚧 **Directories only, never your code** — no import rewriting, no path
  patching, no touching `AGENTS.md`; a move that would break references is
  **reported and refused**, not silently "fixed"
- 📁 **One layout for everything** — per-methodology, per-experiment
  separation of `code/` and `results/`
- 🧭 **Your hierarchy, your call** — default `methods/experiments`, or any
  depth you define: `datasets/methods/experiments`, `phases/trials`, …
- ⚖️ **Size watchdog** — scans `results/` against a threshold (default
  **100MB**) and flags offload candidates with a distinct exit code
- 💾 **HDD offload** — moves big results to a secondary drive and leaves a
  **junction/symlink** behind, so every code path keeps working
- 🙋 **Approval-first** — anything that deletes source data or relocates data hard-fails without
  `--yes`; your agent must ask you first
- 🛡️ **Verified transfers** — copy, SHA-256 tree verification, then source
  deletion; capacity is checked before transfer
- ↩️ **Undoable** — `adopt` and `rm` are journalled; `rm` moves data to an HDD
  trash instead of deleting it, and git guards the rest
- 🧹 **Self-cleaning** — repairs broken links, reports orphans, prunes empty
  dirs; **never auto-deletes data**
- 🪶 **Zero runtime dependencies** — small Python CLI, no database, no DVC

## Recommended for new projects

Directerior is built for projects that start under its layout, and `init`
refuses a directory that already holds a real source tree (`--allow-existing`
overrides). The reason is simple: moving a directory takes a millisecond,
while keeping every import, hardcoded path, config, notebook, and shell script
in sync with that move is an open-ended code-editing problem — and this tool
deliberately refuses to edit your code.

Already have a mature repository? Keep the code where it is and let
Directerior manage only the artifacts:

```bash
python scripts/expman.py adopt ./outputs my-method exp01 --link --yes
python scripts/expman.py offload my-method exp01 --yes
```

## How it works

```
project/                        # root = where .expman.json lives
├── .expman.json                # { "hdd_root": "D:/exp-archive", "threshold_mb": 100 }
└── methods/
    └── lora-finetune/          # one methodology
        └── experiments/
            └── exp01-baseline/ # one run/variant
                ├── 1_plan/         # objective, hypotheses, protocol, decisions
                ├── 2_code/         # scripts + configs for this experiment
                ├── 3_results/      # every artifact goes here
                └── manifest.json
```

When `results/` grows past the threshold and you approve the offload:

```
 SSD (fast, small)                          HDD (big, roomy)
 methods/.../exp01/results  ──junction──▶   exp-archive/project/methods/.../exp01/results
        ▲
        └─ your code keeps reading/writing this exact path — nothing breaks
```

Junctions need **no admin rights** on Windows; POSIX uses symlinks.

## Quickstart

```bash
cd my-project
python scripts/expman.py init --hdd-root D:/exp-archive --threshold-mb 100
python scripts/expman.py new lora-finetune exp01-baseline -d "baseline"

# ... run experiments, write outputs to results/ ...

python scripts/expman.py scan                  # exit 2 = offload candidates
python scripts/expman.py offload lora-finetune exp01-baseline --yes
python scripts/expman.py status
```

## Custom hierarchy

Two levels (`methods` → `experiments`) is the default, not the limit — define
any hierarchy at init:

```bash
python scripts/expman.py init --hdd-root D:/exp-archive --hierarchy datasets,methods,experiments
# datasets/<dataset>/methods/<method>/experiments/<experiment>/{code,results}
```

Every command then takes one name per level, in order:

```bash
python scripts/expman.py new imagenet lora-finetune exp01-baseline
python scripts/expman.py offload imagenet lora-finetune exp01-baseline --yes
```

The hierarchy is stored in `.expman.json`. Pick it once at init — changing it
after data exists means migrating directories manually.

## Commands

| Command | Purpose |
|---|---|
| `init --hdd-root PATH [--threshold-mb N] [--hierarchy a,b,c] [--allow-existing]` | one-time setup at project root |
| `new <name...> [-d DESC]` | scaffold numbered plan/code/results sections |
| `add <parent> <slug> [--group N] [--file]` | create next `N_slug` or `N_a_slug` |
| `scan [--json]` | list local `results/` over threshold (exit 2 if any) |
| `offload <name...> --yes` | move `results/` to HDD, link back |
| `restore <name...> --yes` | verified copy back; delete HDD source after approval |
| `rename <old...> --to <new...> --yes` | rename local leaf and HDD mirror together |
| `rm <name...> --yes [--purge]` | move local leaf and HDD copy to the HDD trash; `--purge` deletes permanently |
| `adopt <path> <name...> [--as NAME] [--link] [--allow-breaking-refs] --yes` | bring an out-of-place output under management; `--link` keeps the original path alive |
| `clean [--fix]` | prune empty HDD dirs, repair broken links, report orphans and trash |
| `migrate-layout [--dry-run] --yes` | preview or convert legacy leaves |
| `history [--json]` | list reversible operations (migrations, `adopt`, `rm`) |
| `undo [ID|latest] --yes` | strictly reverse a migration, an `adopt`, or an `rm` |
| `redo [ID|latest] --yes` | strictly reapply an undone migration |
| `status [--json]` | every experiment: bytes and local/HDD location |

Every data-relocating command also accepts `--allow-dirty` (see below).

## Unexpected output paths

Tools love hardcoded paths (`./outputs/`, `./wandb/`, `~/runs/`). When an
artifact lands outside the layout, the agent contract in
[SKILL.md](SKILL.md) requires **asking you** — with numbered options (adopt,
adopt + link-back, `_shared` method, leave as-is, or type a custom target) —
instead of moving things silently.

`adopt --link` is the trick for stubborn tools: the artifact moves into
`results/`, and a junction at the original path keeps the tool working.

## The reference guard

`adopt` without `--link` first scans your project for text references to the
path it is about to move — and, for code sections, for `import <module>`
lines. Any hit aborts the move and prints exactly what would break:

```text
ERROR: moving /home/me/proj/outputs would break 2 reference(s):
  train.py:14: OUT = "outputs/checkpoints"
  AGENTS.md:52: outputs/ holds every checkpoint
  directerior does not rewrite code, configs, or docs.
  Use --link to keep the original path working, fix the references yourself,
  or pass --allow-breaking-refs to move anyway.
```

It reports; it never repairs. Rewriting imports and path strings is a codemod
with silent failure modes — wrong paths do not raise, they quietly produce
empty results — so that decision stays yours.

## Git as the transaction boundary

In a git repository, relocating commands refuse to run while **tracked** files
are modified, so `git reset --hard` remains a valid escape hatch. Untracked
files — results, checkpoints — never block, because git could not restore them
anyway; the operation journal covers those instead. `--allow-dirty` overrides.

## New and existing projects

New projects get `1_plan/`, `2_code/`, and `3_results/` automatically.
Existing Directerior projects can run `migrate-layout --yes`. Arbitrary
existing codebases are out of scope by design — see
[Recommended for new projects](#recommended-for-new-projects).

Numbering stays simple until complexity needs subdivision:
`1_baseline`, `2_training`; parallel variants under stage 1 become
`1_a_baseline`, `1_b_augmented`. `add` calculates these prefixes.

## Strictly reversible operations

Journals live **outside the project** in the user's Directerior state
directory, so undo leaves no bookkeeping files inside the restored project.
Two kinds share one `history`:

| Kind | Commands | Verification | Reversal |
|---|---|---|---|
| migration | `migrate-layout` | full SHA-256 content | `undo` + `redo` |
| path operation | `adopt`, `rm` | path/size structure | `undo` (re-run to reapply) |

`rm` moves the experiment and its HDD copy to
`<hdd_root>/.trash/<project>/<operation-id>/` rather than deleting them, and
`undo` puts them back — offload link included. `--purge` is the only command
that destroys data outright.

`migrate-layout` first supports `--dry-run`.

Before undo or redo, Directerior verifies:

- exact `.expman.json` bytes;
- every touched file's relative path, byte size, and SHA-256 content;
- empty directory structure;
- local versus HDD location and junction/symlink state.

If anything changed after migration/undo, the command refuses before moving
anything. Successful undo restores original names, bytes, config formatting,
HDD paths, and links. `history`, `undo`, and `redo` default to `latest`.

Every schema-v2 journal is also a future version-graph edge:

```text
parent_id -> operation_id
before_fingerprint -> after_fingerprint
operation_type = migrate_layout
```

Fingerprints describe project state, not command wording, so future rename,
offload, or layout operations can join the same graph when their resulting
state matches the next operation's input state. Older schema-v1 journals stay
readable; Directerior derives missing fingerprints when loading them.

## Team usage

Commit `.expman.json` (shared layout + threshold). Each member points at
their own drive with an environment variable, which overrides the config:

```bash
set EXPMAN_HDD_ROOT=E:\my-archive      # Windows
export EXPMAN_HDD_ROOT=/mnt/archive    # POSIX
```

Offloaded data lands under `<hdd_root>/<project-name>/…`, so one archive
drive serves many projects without collisions.

## Safety invariants

- `offload`, `restore`, `rename`, `rm`, `adopt`, `migrate-layout`, `undo`,
  and `redo` **hard-fail without
  `--yes`** — every source deletion or relocation requires explicit approval
- Offload/restore copy first, verify the complete tree by SHA-256, then delete
  source data; insufficient capacity aborts before copying
- **Source code is never rewritten** — broken references are reported, refused,
  and left to you
- **Agent instruction files** (`AGENTS.md`, `CLAUDE.md`, `.claude/`, …) are
  refused as move or delete targets
- A dirty tracked git worktree blocks relocation unless `--allow-dirty`
- `rm` is undoable through the HDD trash; only `--purge` destroys data
- No silent overwrites — existing targets are always refused
- `restore` / `clean --fix` remove only links and empty dirs, never data
- Orphaned HDD copies are **reported, never auto-deleted**

## License

[MIT](LICENSE) © HSoo-Kim
