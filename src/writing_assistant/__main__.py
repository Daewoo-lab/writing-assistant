"""Entry point stub. The Telegram bot (brief in -> draft out, no credential
collection, no external submission) is wired here when added."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--help" in args or not args:
        print("writing-assistant: send a brief, get a draft. (bot runner not yet wired)")
        return 0
    print(f"unknown args: {args}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
