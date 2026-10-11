#!/usr/bin/env python3
"""Classify a Git diff for the repository's CI workflow."""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


AUTOMATIC_EVENTS = frozenset({"pull_request", "push"})
MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})
SAFE_DOCS_SUFFIXES = MARKDOWN_SUFFIXES | frozenset(
    {
        ".adoc",
        ".gif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".pdf",
        ".png",
        ".rst",
        ".svg",
        ".txt",
        ".webp",
    }
)


@dataclass(frozen=True)
class Classification:
    docs_only: bool
    paths: tuple[str, ...]
    base_sha: str = ""
    head_sha: str = ""


def resolve_revision(repo: Path, revision: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{revision}^{{commit}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def changed_paths(repo: Path, base: str, head: str) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            base,
            head,
            "--",
        ],
        check=True,
        capture_output=True,
    )
    return [
        raw.decode("utf-8", errors="strict")
        for raw in result.stdout.split(b"\0")
        if raw
    ]


def is_docs_path(path: str) -> bool:
    candidate = Path(path)
    suffix = candidate.suffix.lower()
    if suffix in MARKDOWN_SUFFIXES:
        return True
    return path.startswith("docs/") and suffix in SAFE_DOCS_SUFFIXES


def is_docs_only(paths: Iterable[str]) -> bool:
    changed = tuple(paths)
    return bool(changed) and all(is_docs_path(path) for path in changed)


def classify(
    repo: Path,
    *,
    event_name: str,
    base: str = "",
    head: str = "",
) -> Classification:
    if event_name not in AUTOMATIC_EVENTS:
        return Classification(docs_only=False, paths=())
    if not base or not head:
        raise ValueError(f"{event_name} classification requires base and head revisions")

    base_sha = resolve_revision(repo, base)
    head_sha = resolve_revision(repo, head)
    paths = tuple(changed_paths(repo, base_sha, head_sha))
    return Classification(
        docs_only=is_docs_only(paths),
        paths=paths,
        base_sha=base_sha,
        head_sha=head_sha,
    )


def write_github_output(destination: Path, result: Classification) -> None:
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(f"docs_only={'true' if result.docs_only else 'false'}\n")
        handle.write(f"change_count={len(result.paths)}\n")
        handle.write(f"base_sha={result.base_sha}\n")
        handle.write(f"head_sha={result.head_sha}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    result = classify(
        args.repo.resolve(),
        event_name=args.event_name,
        base=args.base,
        head=args.head,
    )
    print(
        f"change scope: event={args.event_name} "
        f"docs_only={'true' if result.docs_only else 'false'} "
        f"changed_paths={len(result.paths)}"
    )
    for path in result.paths:
        print(path)

    if args.github_output is not None:
        write_github_output(args.github_output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
