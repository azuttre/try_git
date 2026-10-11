# Recovery maintenance

Every source change must assess machine replacement impact: installation, runtime
dependencies, credentials, durable state, backups, restore, scheduling and host
placement. Update the authoritative owner procedure in the same change when any
requirement changes. DSM manual changes are outside this gate's scope.

The offline CI check requires one exact-change disposition under
`.machine-recovery/changes/`. Run:

```sh
python3 .machine-recovery/check.py --base origin/master --head HEAD --digest
python3 .machine-recovery/test_check.py
python3 .machine-recovery/check.py --base origin/master --head HEAD
```

Copy `diff_sha256` into a new JSON record with `repository` set to
`azuttre/try_git`, `disposition` set to `updated` or `not-applicable`,
and a concrete `reason` explaining replacement impact. For `updated`, list changed
authoritative Markdown paths in `owned_records`. Regenerate the digest after every
source edit; only changed committed dispositions count. `--staged --base BASE`
checks staged bytes without accepting an unstaged correction.

A recovery-affecting update also requires the repository owner's consolidated
machine catalog/runbook update to land before merge. The owner merge guard verifies
that catalog's `repo-try-git` component has `last_change["try_git"]`
equal to this disposition digest. `not-applicable` needs a substantive explanation,
reviewed for accuracy, and does not require a meaningless central prose edit.

CI runs this stdlib-only check in both documentation and full lanes; no credentials,
private catalog download, live services or DSM inspection. Manual/scheduled checks
validate policy/reference completeness without claiming an exact-change disposition.
The retained generated-data exclusions, if any, are in `policy.json`; its baseline
version governs the diff so a change cannot exempt itself. Configuration changes
require coordinated owner review and policy pin maintenance.

## Setup and source ownership

Python 3.10+ and Git suffice. No application runtime or extra package install is
required for this check. Existing owner docs below retain installation, protected
state custody and restore authority. Keep credentials and private evidence outside Git.
