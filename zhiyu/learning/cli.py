"""本机审核话术记忆。令牌只从环境读取，不能写在命令参数里。通话口令不能审核。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from zhiyu.learning.store import LearningRejected, LearningStore


def main(argv: list[str] | None = None) -> int:
    token = os.environ.get("ZHIYU_ADMIN_TOKEN", "").strip()
    if len(token) < 16:
        print("需要环境里的管理员令牌。通话口令不能审核。", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description="审核已脱敏的场景话术候选")
    parser.add_argument("--dir", default=os.environ.get("ZHIYU_LEARNING_DIR", "var/learning"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    approve = sub.add_parser("approve")
    approve.add_argument("item_id")
    approve.add_argument("--speak", required=True)
    for name in ("reject", "disable", "rollback"):
        command = sub.add_parser(name)
        command.add_argument("item_id")
    args = parser.parse_args(argv)
    store = LearningStore(Path(args.dir))
    try:
        if args.command == "list":
            for item in store.list_items():
                print(f"{item['id']} row={item['source_row']} {item['status']} v{item['version']} {item.get('note','')}")
            return 0
        if args.command == "approve":
            item = store.approve(args.item_id, args.speak)
        elif args.command == "reject":
            item = store.reject(args.item_id)
        elif args.command == "disable":
            item = store.disable(args.item_id)
        else:
            item = store.rollback(args.item_id)
    except LearningRejected as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"{item['id']} {item['status']} v{item['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
