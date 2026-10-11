#!/usr/bin/env python3
"""Portable, offline same-change recovery gate. Canonical source: personal-context.

Vendored byte-for-byte into .machine-recovery/check.py in owned repositories.
No network, credentials, application imports or live configuration inspection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

POLICY = '.machine-recovery/policy.json'
CHANGES = '.machine-recovery/changes/'


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.PIPE)


def read(root, ref, path):
    return git(root, 'show', f'{ref}:{path}')


def tree(root, ref):
    if ref == '':
        rows = git(root, 'ls-files', '--stage', '-z').split(b'\0')
        result = {}
        for row in filter(None, rows):
            metadata, path = row.split(b'\t', 1)
            mode, sha, stage = metadata.decode().split()
            if stage != '0':
                raise ValueError('unmerged index cannot establish recovery evidence')
            result[path.decode()] = [mode, sha]
        return result
    result = {}
    for row in filter(None, git(root, 'ls-tree', '-r', '-z', ref).split(b'\0')):
        metadata, path = row.split(b'\t', 1)
        mode, kind, sha = metadata.decode().split()
        result[path.decode()] = [mode, sha]
    return result


def validate_policy(policy, paths):
    if policy.get('schema_version') != 1 or not isinstance(policy.get('repository'), str):
        raise ValueError('invalid recovery policy')
    records = policy.get('owned_records')
    if not isinstance(records, list) or not records:
        raise ValueError('policy must name authoritative recovery records')
    for path in records:
        if not isinstance(path, str) or not path.endswith('.md') or path not in paths:
            raise ValueError(f'missing authoritative recovery record: {path}')
    for key in ('generated_paths', 'evidence_paths'):
        excluded = policy.get(key, [])
        if not isinstance(excluded, list) or any(not isinstance(x, str) or not x for x in excluded):
            raise ValueError(f'invalid {key.replace("_", "-")} policy')


def changed_paths(before, after):
    return sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))


def change_digest(before, after, policy):
    # Blob IDs, modes and paths are reproducible across diff/CRLF/rename settings.
    paths = [p for p in changed_paths(before, after)
             if not p.startswith(CHANGES)
             and not any(p.startswith(x) for x in
                         policy.get('generated_paths', []) + policy.get('evidence_paths', []))]
    payload = [[p, before.get(p), after.get(p)] for p in paths]
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
    return paths, digest


def validate_receipt(policy, paths, digest, receipts, changed):
    if not paths:
        return None
    matches = [r for r in receipts if r.get('repository') == policy['repository']
               and r.get('diff_sha256') == digest]
    if len(matches) != 1:
        raise ValueError(f'exact change requires one recovery disposition: {digest}')
    receipt = matches[0]
    if not isinstance(receipt.get('reason'), str) or len(receipt['reason'].strip()) < 30:
        raise ValueError('disposition requires a concrete recovery-impact explanation')
    mode = receipt.get('disposition')
    if mode not in {'updated', 'not-applicable'}:
        raise ValueError('disposition must be updated or not-applicable')
    if mode == 'updated':
        records = receipt.get('owned_records', [])
        if not records or any(p not in policy['owned_records'] or p not in changed for p in records):
            raise ValueError('updated requires changed authoritative recovery documentation')
    return receipt


def inspect(root, base, head='HEAD', staged=False):
    merge_base = git(root, 'merge-base', base, 'HEAD' if staged else head).decode().strip()
    ref = '' if staged else head
    before, after = tree(root, merge_base), tree(root, ref)
    policy = json.loads(read(root, ref, POLICY))
    validate_policy(policy, after)
    # Existing policy governs this diff; a PR cannot exempt itself by widening exclusions.
    baseline = json.loads(read(root, merge_base, POLICY)) if POLICY in before else policy
    validate_policy(baseline, before if POLICY in before else after)
    if policy['repository'] != baseline['repository']:
        raise ValueError('repository identity changed')
    paths, digest = change_digest(before, after, baseline)
    changed = changed_paths(before, after)
    receipts = [json.loads(read(root, ref, p)) for p in changed
                if p.startswith(CHANGES) and p.endswith('.json') and p in after]
    return policy, paths, digest, receipts, set(changed), baseline


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--base')
    parser.add_argument('--head', default='HEAD')
    parser.add_argument('--staged', action='store_true')
    parser.add_argument('--digest', action='store_true')
    parser.add_argument('--event-name')
    parser.add_argument('--repository')
    args = parser.parse_args(argv)
    root = args.repo.resolve()
    if args.event_name in {'workflow_dispatch', 'schedule'}:
        policy = json.loads(read(root, args.head, POLICY))
        validate_policy(policy, tree(root, args.head))
        print('Recovery policy and owner references passed; no change disposition claimed.')
        return 0
    base = args.base
    if args.staged and not base:
        base = 'origin/' + git(root, 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD').decode().strip().split('/', 1)[1]
    if not base or set(base) == {'0'}:
        raise ValueError('automatic change validation requires a nonempty base commit')
    policy, paths, digest, receipts, changed, baseline = inspect(root, base, args.head, args.staged)
    if args.repository and policy['repository'] != args.repository:
        raise ValueError('workflow repository does not match recovery policy')
    if args.digest:
        print(json.dumps({'repository':policy['repository'], 'diff_sha256':digest, 'paths':paths}, indent=2))
        return 0
    validate_receipt(policy, paths, digest, receipts, changed)
    print('Exact-change recovery disposition and authoritative records passed.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'machine-recovery: failed closed: {exc}', file=sys.stderr)
        raise SystemExit(1)
