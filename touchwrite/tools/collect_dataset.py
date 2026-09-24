"""Create and populate guided local handwriting collection sessions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from touchwrite.collection.session import add_sample, collection_status, create_session


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    initialize = subparsers.add_parser("init", help="create a prompt queue")
    initialize.add_argument("--root", type=Path, default=Path("data/collection"))
    initialize.add_argument("--participant", default="local-user")
    initialize.add_argument("--repeats", type=int, default=3)
    initialize.add_argument("--session-id")

    add = subparsers.add_parser("add", help="label an existing immutable sample")
    add.add_argument("session", type=Path)
    add.add_argument("sample_id")
    add.add_argument("label")
    add.add_argument("--handwriting-root", type=Path, default=Path("data/handwriting"))

    status = subparsers.add_parser("status", help="show progress and the next prompt")
    status.add_argument("session", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "init":
        session_dir = create_session(
            args.root,
            participant=args.participant,
            repeats=args.repeats,
            session_id=args.session_id,
        )
        result = {"session": str(session_dir), **collection_status(session_dir)}
    elif args.command == "add":
        record = add_sample(args.session, args.handwriting_root, args.sample_id, args.label)
        result = {"added": record, **collection_status(args.session)}
    else:
        result = collection_status(args.session)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
