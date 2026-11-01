"""Command-line entry point.

abshelver organize          scan the library, print every issue and the
                            ordered ops that would fix it; exit 1 if any
abshelver organize --doit   the same, then apply all of them
"""

import argparse
import logging
import sys
from pathlib import PurePosixPath

from abshelver import audit, library, organizer
from abshelver.audit import Issue
from abshelver.config import ConfigError, get_settings
from abshelver.ops import OpError


def print_issues(lib: library.Library, issues: list[Issue]) -> None:
    blocks: dict[PurePosixPath, list[Issue]] = {}
    for issue in issues:
        blocks.setdefault(issue.block, []).append(issue)
    for block, items in blocks.items():
        print(f"{block}/")
        for issue in items:
            if issue.dst is not None and issue.src is not None:
                print(
                    f"  {issue.kind:<11} {issue.src.name if issue.kind != 'folder' else issue.src}"
                )
                print(
                    f"  {'':<11} → {issue.dst.name if issue.kind != 'folder' else issue.dst}"
                )
            elif issue.src is not None:
                print(f"  {issue.kind:<11} {issue.src.name}")
            else:
                print(f"  {issue.kind:<11} ({issue.note})")
            if issue.note and issue.src is not None:
                print(f"  {'':<11} {issue.note}")
            if issue.blocked:
                print(f"  {'':<11} Not applicable: {issue.blocked}")
        print()
    clean = audit.clean_count(lib, issues)
    print(f"{len(lib.books)} books, {clean} clean, {len(issues)} issues")


def cmd_organize(doit: bool) -> int:
    settings = get_settings()
    settings.check()
    lib, issues = organizer.rescan(settings.library_dir)
    print_issues(lib, issues)
    selected = [i.id for i in issues if i.actionable]
    ops = organizer.plan(lib, issues, selected)
    if ops:
        print()
        print("ops:")
        for op in ops:
            print(f"  {op.line}")
    if not doit:
        return 1 if selected else 0
    if not ops:
        print("Nothing to apply")
        return 0
    print()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout
    )
    try:
        organizer.apply(settings.library_dir, selected)
    except (OpError, organizer.PlanError) as exc:
        print(f"Aborted: {exc}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="abshelver",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    org = sub.add_parser("organize", help="audit the library against the naming schema")
    org.add_argument(
        "--doit",
        action="store_true",
        help="apply every proposed op (the dry run is the confirmation)",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "organize":
            return cmd_organize(args.doit)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
