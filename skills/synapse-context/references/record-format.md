# Record format v0.1

This is a lightweight convention, not an implemented event API or a compatibility promise. Store one JSON record per run, with start/end manifests alongside it. Use UTF-8. Validate JSON syntax and verify the invariants below before handing a record to another task.

Required record groups:

| Group | Fields and meaning |
| --- | --- |
| Identity | schema_version, run_id; unique local record identity |
| Conversation | native_session_id, native_turn_id, parent_session_id, fork_anchor; nullable and based only on observed host data |
| Workspace | local workspace binding, optional git_head; HEAD never substitutes for uncommitted file state |
| Baseline | captured_at, manifest_ref, coverage, fork_base_known |
| Changes | path, operation, before/after hash, purpose, lifecycle, attribution, evidence_refs |
| Completion | state, ended_at, checks, omissions |

Local workspace bindings map an alias to an actual directory outside the shareable record. This avoids hard-coding machine paths into examples. A manifest records relative paths, a declared hash algorithm, hashes, and unreadable/omitted entries; preserve the start manifest rather than overwriting it at finish.

Invariants:

1. Null means unknown or unavailable, not a fabricated value. For a created file, before_hash can be null only when a baseline actually proves absence; otherwise mark the operation unknown. The same distinction applies to deleted files and missing after_hash.
2. Use `attribution: observed_only` for snapshot differences without execution evidence. `linked_operation` requires an actual evidence reference connecting an operation to the run. Neither classification proves exclusive authorship under concurrent writers.
3. Missing manifests, inaccessible paths, late tracking, or unknown fork-time state belong in coverage/omissions. `complete` means this observation record is closed, not that the development task succeeded.
4. A hash verifies observed content identity; it is neither a backup nor proof of semantic accuracy. Keep optional content snapshots only within the user's authorized scope.
5. Git HEAD, a tool call, and a native session ID use distinct reference types. Do not turn a model statement such as “tests passed” into a verified test result.
6. Shared-directory concurrency is disclosed. Independent run files avoid competing append operations, but they do not isolate edits to project files.

The following deliberately incomplete record is fictional. No snapshot or tool execution is claimed:

```json
{
  "schema_version": "0.1",
  "run_id": "example-csv-investigation",
  "conversation": {
    "native_session_id": null,
    "native_turn_id": null,
    "parent_session_id": null,
    "fork_anchor": null
  },
  "workspace": {"binding": "example-project", "git_head": null},
  "baseline": {
    "captured_at": null,
    "manifest_ref": null,
    "coverage": "missing",
    "fork_base_known": false
  },
  "changes": [],
  "resource_notes": [
    {
      "path": "experiments/reproduce_csv_error.py",
      "purpose": "Candidate script for reproducing a CSV encoding error",
      "lifecycle": "temporary",
      "source": "agent_suggestion",
      "basis_version": null
    }
  ],
  "completion": {
    "state": "incomplete",
    "ended_at": null,
    "checks": [],
    "omissions": ["Illustrative record only; no files or native session were observed"]
  }
}
```

For an actual run, generate manifests from actual observations and add change entries only after comparison. On handoff, check referenced versions before trusting a prior purpose or summary.
