#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import NoReturn

from directerior_core import DEFAULT_HIERARCHY, DirecteriorError, find_root, load_config
from directerior_history import (
    MigrationRecord,
    list_operation_records,
    list_records,
    show_history,
)
from directerior_lifecycle import (
    clean,
    offload,
    remove_experiment,
    rename_experiment,
    restore,
)
from directerior_migrate import (
    migrate_layout,
    redo_migration,
    undo_migration,
)
from directerior_ops import recover_operation, undo_operation
from directerior_project import (
    add_numbered,
    adopt_output,
    create_experiment,
    initialize,
    scan_entries,
    status_entries,
    upgrade_config,
)


def assert_never(value: NoReturn) -> NoReturn:
    raise AssertionError(f"unreachable command: {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="directerior",
        description="Lightweight research experiment directory manager.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    names_help = "one name per configured hierarchy level"

    command = subcommands.add_parser("init")
    command.add_argument("--hdd-root", required=True)
    command.add_argument("--threshold-mb", type=int, default=100)
    command.add_argument("--hierarchy", default=",".join(DEFAULT_HIERARCHY))
    command.add_argument("--allow-existing", action="store_true")

    command = subcommands.add_parser("new")
    command.add_argument("names", nargs="+", help=names_help)
    command.add_argument("-d", "--description", default="")

    command = subcommands.add_parser("scan")
    command.add_argument("--json", action="store_true")

    command = subcommands.add_parser("status")
    command.add_argument("--json", action="store_true")
    command.add_argument("--verify", action="store_true")

    for name in ("offload", "restore", "rm"):
        command = subcommands.add_parser(name)
        command.add_argument("names", nargs="+", help=names_help)
        command.add_argument("--yes", action="store_true")
        command.add_argument("--allow-dirty", action="store_true")
        if name == "rm":
            command.add_argument("--purge", action="store_true")

    command = subcommands.add_parser("rename")
    command.add_argument("names", nargs="+", help=names_help)
    command.add_argument("--to", nargs="+", required=True, dest="new_names")
    command.add_argument("--yes", action="store_true")
    command.add_argument("--allow-dirty", action="store_true")

    command = subcommands.add_parser("clean")
    command.add_argument("--fix", action="store_true")

    command = subcommands.add_parser("adopt")
    command.add_argument("source")
    command.add_argument("names", nargs="+", help=names_help)
    command.add_argument("--as", dest="destination_name", default="")
    command.add_argument("--link", action="store_true")
    command.add_argument("--section", choices=("plan", "code", "results"), default="results")
    command.add_argument("--yes", action="store_true")
    command.add_argument("--allow-breaking-refs", action="store_true")
    command.add_argument("--allow-dirty", action="store_true")

    command = subcommands.add_parser("migrate-layout")
    command.add_argument("--yes", action="store_true")
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--allow-dirty", action="store_true")

    command = subcommands.add_parser("upgrade-config")
    command.add_argument("--yes", action="store_true")
    command.add_argument("--allow-dirty", action="store_true")

    command = subcommands.add_parser("history")
    command.add_argument("--json", action="store_true")

    for name in ("undo", "redo"):
        command = subcommands.add_parser(name)
        command.add_argument("operation_id", nargs="?", default="latest")
        command.add_argument("--yes", action="store_true")

    command = subcommands.add_parser("recover")
    command.add_argument("operation_id", nargs="?", default="latest")
    command.add_argument("--yes", action="store_true")

    command = subcommands.add_parser("add")
    command.add_argument("parent")
    command.add_argument("slug")
    command.add_argument("--group", type=int)
    command.add_argument("--file", action="store_true")
    return parser


def undo_any(operation_id: str, approved: bool) -> None:
    root = find_root()
    operations = list_operation_records(root)
    migrations = list_records(root)
    if operation_id == "latest":
        candidates = [*operations, *migrations]
        if not candidates:
            raise DirecteriorError("no operation history for this project")
        record = max(candidates, key=lambda item: item.created_at)
    else:
        matches = [
            *(record for record in operations if record.operation_id == operation_id),
            *(record for record in migrations if record.operation_id == operation_id),
        ]
        if not matches:
            raise DirecteriorError(f"operation history not found: {operation_id}")
        record = matches[0]
    if isinstance(record, MigrationRecord):
        undo_migration(record.operation_id, approved)
    else:
        undo_operation(root, record.operation_id, approved)


def run(arguments: argparse.Namespace) -> int:
    match arguments.command:
        case "init":
            initialize(
                arguments.hdd_root,
                arguments.threshold_mb,
                arguments.hierarchy,
                arguments.allow_existing,
            )
        case "new":
            create_experiment(arguments.names, arguments.description)
        case "scan":
            root = find_root()
            config = load_config(root)
            entries = scan_entries(root, config)
            if arguments.json:
                print(json.dumps({"threshold_mb": config.threshold_mb, "entries": entries}))
            else:
                for entry in entries:
                    print(f"{entry['label']}  {entry['bytes']} bytes")
            return 2 if entries else 0
        case "status":
            root = find_root()
            config = load_config(root)
            entries = status_entries(root, config, arguments.verify)
            if arguments.json:
                print(json.dumps({"threshold_mb": config.threshold_mb, "entries": entries}))
            else:
                for entry in entries:
                    line = f"{entry['label']}  {entry['location']}  {entry['bytes']} bytes"
                    if arguments.verify:
                        line += f"  verified sha256={entry['digest']}"
                    print(line)
        case "offload":
            offload(arguments.names, arguments.yes, arguments.allow_dirty)
        case "restore":
            restore(arguments.names, arguments.yes, arguments.allow_dirty)
        case "rename":
            rename_experiment(
                arguments.names,
                arguments.new_names,
                arguments.yes,
                arguments.allow_dirty,
            )
        case "rm":
            remove_experiment(
                arguments.names,
                arguments.yes,
                arguments.purge,
                arguments.allow_dirty,
            )
        case "clean":
            return clean(arguments.fix)
        case "adopt":
            adopt_output(
                arguments.source,
                arguments.names,
                arguments.destination_name,
                arguments.link,
                arguments.yes,
                arguments.section,
                arguments.allow_breaking_refs,
                arguments.allow_dirty,
            )
        case "migrate-layout":
            migrate_layout(arguments.yes, arguments.dry_run, arguments.allow_dirty)
        case "upgrade-config":
            upgrade_config(arguments.yes, arguments.allow_dirty)
        case "history":
            show_history(find_root(), arguments.json)
        case "undo":
            undo_any(arguments.operation_id, arguments.yes)
        case "redo":
            redo_migration(arguments.operation_id, arguments.yes)
        case "recover":
            record = recover_operation(find_root(), arguments.operation_id, arguments.yes)
            print(f"recovered {record.operation_type}; operation={record.operation_id}")
        case "add":
            add_numbered(arguments.parent, arguments.slug, arguments.group, arguments.file)
        case unreachable:
            assert_never(unreachable)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(build_parser().parse_args(argv))
    except DirecteriorError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
