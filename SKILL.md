---
name: directerior
description: Lightweight per-method/per-experiment directory manager with HDD offload for large results. Recommended for projects it lays out from the start; it moves directories but never rewrites source code, imports, or agent instruction files. MUST USE when creating a new experiment, organizing experiment outputs, when results/artifacts pile up in a research project, when the user wants their own directory scheme, or when outputs land in unexpected paths. Manages a configurable hierarchy (default methods/<method>/experiments/<experiment>) of {code,results} dirs, scans results dirs against a size threshold (default 100MB), and - ONLY after explicit user approval - moves oversized results to a configured HDD and junction-links them back so code paths keep working. Adopts out-of-place outputs after asking the user, repairs broken links, prunes empty HDD dirs. Triggers: directerior, new experiment, organize experiments, experiment directory, results too big, offload results, move results to HDD, restore results, adopt outputs, unexpected output path, experiment status, clean experiment dirs, 실험 디렉토리, 실험 정리, 결과물 정리, 결과물 HDD 이동, 방법론별 실험 관리, 예상치 못한 경로, custom hierarchy, directory scheme, 계층 구조, 원하는 디렉토리 구조.
---

# directerior

Lightweight experiment directory manager. No database, no DVC - just a fixed
folder convention plus Windows junctions (POSIX symlinks) for HDD offload.
Requires Python 3.10+. Junctions need no admin rights on Windows.

## Non-goals - what this skill never does

Directerior moves directories. It never changes the meaning of a file.

- **Never rewrites source code.** No import rewriting, no path-string patching,
  no codemods. A directory move that would break references is reported and
  refused, never repaired.
- **Never edits agent instruction files.** `AGENTS.md`, `CLAUDE.md`,
  `.claude/`, `.cursor/`, `SKILL.md` and friends are refused as move or delete
  targets. If reorganizing makes a doc stale, say so and let the user decide;
  do not silently rewrite their paths.
- **Never restructures an existing codebase.** `init` refuses a directory that
  already holds a real source tree.

Moving code is cheap; keeping every import, hardcoded path, SUMO/Hydra config,
notebook, and shell script in sync with the move is not. Directerior manages
the directories it created and leaves everything else alone.

## Recommended for new projects

Use directerior on a project **from its start**, so every artifact is born in
the managed layout. Tell the user this explicitly when they ask to apply it to
an established repository.

For an existing codebase, recommend the narrow, safe subset instead:

1. Leave the source tree exactly where it is.
2. Manage only the large outputs - `adopt --link` for hardcoded output paths,
   then `offload` when they cross the threshold.
3. If they still want a full layout, that is a manual migration they own; you
   may help with it, but not through directerior, and not silently.

Use the installed `directerior <command>` entry point. When operating directly
from a checked-out skill repository, the supported fallback is
`python <skill-dir>/scripts/expman.py <command>`. Run from anywhere inside the
project; the CLI finds `.expman.json` upward.

## Managed layout

```
project/                      # root = where .expman.json lives
├── .expman.json              # schema 2 config + collision-resistant project_id
└── methods/
    └── <method>/             # one methodology, e.g. "lora-finetune"
        └── experiments/
            └── <experiment>/ # one run/variant, e.g. "exp01-baseline"
                ├── 1_plan/       # numbered design documents
                ├── 2_code/       # scripts + configs for this experiment
                ├── 3_results/    # outputs; offloadable
                └── manifest.json # method, experiment, created, description
```

Schema-2 projects mirror under `<hdd_root>/<project-name>--<project_id>/`.
Legacy configs remain readable and retain `<hdd_root>/<project-name>/`.

The two levels above are the default. `.expman.json` may define any hierarchy
(e.g. `"hierarchy": ["datasets", "methods", "experiments"]`); every command
below then takes one name per level, in order.

Rules for the agent:
- Experiment code goes in `code/`, every generated artifact goes in `results/`.
  Never write outputs to the project root or into `code/`.
- Name methods after the methodology, experiments as `expNN-<short-slug>`.
- Shared library code stays outside `methods/` (e.g. `src/`); `code/` holds
  only experiment-specific scripts/configs that import from it.
- If code in one experiment's `code/` gets imported by another experiment,
  promote it to `src/` instead of cross-importing between experiments.
- Artifacts shared by several experiments go in a `_shared` pseudo-method,
  e.g. `new _shared datasets`.
- Multi-user projects: commit `.expman.json` (shared layout + threshold);
  each member overrides the drive location with the `EXPMAN_HDD_ROOT`
  environment variable. Never hardcode another user's drive path.

## Commands

| Command | Purpose |
|---|---|
| `init --hdd-root D:/exp-archive [--threshold-mb 100] [--hierarchy a,b,c] [--allow-existing]` | one-time setup at project root |
| `new <name...> [-d "desc"]` | scaffold `1_plan/2_code/3_results` |
| `add <parent> <slug> [--group N] [--file]` | auto-create `N_slug` or `N_a_slug` |
| `scan [--json]` | list local `results/` over threshold; exit 2 if any |
| `offload <name...> --yes` | move `results/` to HDD + junction back |
| `restore <name...> --yes` | bring `results/` back; auto-prunes empty HDD dirs |
| `rename <old...> --to <new...> --yes` | rename local leaf + HDD mirror safely |
| `rm <name...> --yes` | move local leaf + HDD copy to the HDD trash (undoable) |
| `rm <name...> --yes --purge` | delete permanently instead; no undo |
| `adopt <path> <name...> [--as NAME] [--link] [--section plan\|code\|results] [--allow-breaking-refs] --yes` | move an out-of-place output into the leaf |
| `clean [--fix]` | repair only links whose exact HDD target exists; report unresolved links, orphans, and trash; exit 2 while unresolved |
| `migrate-layout --yes` | convert all legacy `code/results` leaves to numbered sections |
| `migrate-layout --dry-run` | preview every migration path without mutation/history |
| `upgrade-config --yes [--allow-dirty]` | assign a schema-2 project ID after all offloaded results are restored |
| `history [--json]` | list completed and interrupted external journals |
| `recover [ID|latest] --yes` | verify and resume an interrupted forward operation |
| `undo [ID|latest] --yes` | verify and reverse a committed migration, `adopt`, or non-purge `rm` |
| `redo [ID|latest] --yes` | verify and reapply an undone migration |
| `status [--json] [--verify]` | metadata-only sizes by default; `--verify` adds SHA-256 digest |

Every data-relocating command also takes `--allow-dirty`; see the git section.

## Workflow

1. **Project setup** (once): ask the user which HDD path to use (and whether
   they want a custom hierarchy - see below), then `init`.
2. **New experiment**: `new <name...>`, put code in `code/`,
   write outputs to `results/`.
3. **After any run that produced artifacts**: run `scan`.
4. **If scan reports over-threshold experiments (exit 2)**:
   - Report the list and sizes to the user.
   - ASK THE USER for approval to offload. NEVER offload without an explicit
     yes in this conversation. The `--yes` flag is that approval's proof, not
     a default.
   - On approval: `offload <name...> --yes`. Code keeps working -
     the original `results/` path is now a junction to the HDD copy.
5. **When the user wants data back on fast storage**: report that restore
   deletes the verified HDD source after copying, ASK for approval, then
   `restore <name...> --yes`.
6. **Periodically or when links look stale**: run `clean`. Run `clean --fix`
   only after reporting findings; missing targets and regular paths stay unresolved.

## Project setup - which projects qualify

- **New project**: `init`, then `new`; numbered sections and plan files are
  scaffolded automatically. This is the supported path.
- **Existing directerior project using `code/results`**: report planned
  changes, run `migrate-layout --dry-run`, ASK for approval, then
  `migrate-layout --yes`. Report the operation ID and undo command.
- **Existing arbitrary codebase**: `init` refuses it. Do not work around this
  by chaining `adopt` calls to fake a migration. Explain the recommendation
  above, offer the outputs-only subset, and use `--allow-existing` only when
  the user asks for it after hearing that their imports stay their problem.

## Reference guard

`adopt` without `--link` scans the project for text references to the source
path - and, for `--section code|plan`, for `import <module>` lines. Any hit
aborts the move and prints the offending `file:line` list.

When that happens, present the options instead of forcing the move:

1. `--link` - move the data, leave a junction/symlink so every hardcoded path
   keeps working. Preferred for tool-generated output paths.
2. Fix the references yourself, in a separate step the user reviews.
3. `--allow-breaking-refs` - only after the user has seen the list and
   accepted that those references will break.

Hits inside `AGENTS.md` or other docs are reported too. Update that prose
yourself, with judgement; the CLI will not touch it.

## Git as the transaction boundary

In a git project, every data-relocating command refuses to run when *tracked*
files are modified, so `git reset --hard` stays a valid escape hatch. Untracked
files - results, checkpoints - never block, since git could not restore them
anyway; the operation journal covers those.

Commit or stash first. `--allow-dirty` exists for the rare case where the user
knowingly accepts that their uncommitted edits and this move are entangled.

## Strict undo/recovery protocol

Schema-3 journals live outside the project in Directerior's user state
directory. `history` shows both completed and interrupted operations.

`offload`, `restore`, `rename`, `adopt`, `rm`, and `migrate-layout` journal
every filesystem transition. After interruption:

1. Run `history` and identify the requested record (default `latest`).
2. Explain that `recover` verifies exact snapshots, paths, and link targets,
   and resumes the already-approved forward operation only.
3. ASK for fresh approval, then run `recover [ID|latest] --yes`.
4. If state does not match the journal or its exact immediate successor, do
   not bypass the conflict or move files manually.

`undo` accepts only committed records and requires its own fresh approval.
Migrations support `undo` and `redo`; `adopt` and non-purge `rm` support
`undo`. Trash lives under
`<hdd_root>/.trash/<project--project_id>/<operation-id>/`. `rm --purge`
permanently deletes data, records a diagnostic journal, and cannot be undone.

Legacy configs are not rewritten implicitly. `upgrade-config --yes` is the
explicit path to schema 2 and refuses until all offloaded leaves are restored.

## Adaptive numbering

- Simple sequence: `1_plan`, `2_code`, `3_results`; files such as
  `1_objective.md`, `2_hypotheses.md`.
- Parallel variants inside logical stage N: `N_a_<slug>`, `N_b_<slug>`, ...
- Use letters only when real parallel subdivisions exist. Do not decorate
  every name with both prefixes.
- `add <parent> <slug>` chooses next numeric prefix. `--group N` chooses next
  alphabetical subdivision under N (`1_a_`, then `1_b_`, ...).
- If semantic grouping is unclear, show candidate groupings and ask instead
  of choosing a group number silently.

## Unexpected output paths - ASK THE USER

When an output does not fit the managed layout - a tool writes to a hardcoded
path (`./outputs/`, `./wandb/`, `~/runs/...`), an artifact belongs to several
experiments, or results already exist somewhere else - NEVER move it or pick a
location silently. Present numbered options and let the user choose:

1. Adopt into the standard layout: `adopt <path> <name...> --yes`.
2. Adopt but keep the original path working (hardcoded-path tools):
   `adopt <path> <name...> --link --yes` (directories only).
3. Shared artifact: use `_shared` as the first-level name
   (e.g. `new _shared datasets`) then adopt into it.
4. Leave it unmanaged where it is.
5. Somewhere else - ask the user to type the exact target path/experiment.

If none of the offered options fits, request direct input instead of guessing.
`adopt` enforces the same approval discipline as `offload`: `--yes` only after
the user explicitly chose.

## Custom hierarchies - propose and confirm

Default is `methods/experiments`. When the user asks for their own directory
organization (by dataset, phase, model size, seed, ...), do NOT invent a
structure silently:

1. Derive 2-3 candidate hierarchies from what they described, each shown as a
   small example tree (e.g. `datasets,methods,experiments` ->
   `datasets/imagenet/methods/lora/experiments/exp01/`).
2. Let the user pick one or type their own level list.
3. Initialize with `init --hdd-root ... --hierarchy level1,level2,...`.

The hierarchy is fixed once data exists; changing it later means migrating
directories manually (offer to do it - with explicit user approval - by
restoring offloaded results first, moving dirs, then re-offloading).

## Safety invariants

- `offload`, `restore`, `rename`, `rm`, `adopt`, `migrate-layout`, `recover`,
  `undo`, and `redo` without `--yes` always fail. Every operation that deletes,
  relocates, or resumes user data requires explicit approval in the current
  conversation.
- Agent instruction files are never moved, deleted, or rewritten.
- Source code is never rewritten; broken references are reported, not repaired.
- A dirty tracked git worktree blocks relocation unless `--allow-dirty`.
- `rm` is undoable through the HDD trash; only `--purge` destroys data.
- Offload and restore use copy -> SHA-256 tree verification -> source deletion
  -> link/prune. Copy or capacity failure preserves the source.
- Offload/restore check free capacity first and warn when source and target
  share a volume.
- Offload refuses when the HDD target already exists; adopt refuses to
  overwrite an existing destination (no silent overwrite).
- `restore` and `clean --fix` remove only links and empty directories, never
  data. A missing HDD target is not replaced with an empty directory; unresolved
  links and orphaned HDD copies are reported with exit 2.
- Ordinary `scan` and `status` read metadata only. Use `status --verify` for
  explicit SHA-256 verification and digest output.
- Offloaded dirs count as 0 local bytes in `scan`/`status` and show as `HDD`.
