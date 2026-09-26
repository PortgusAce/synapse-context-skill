# Local record format v0.2

The bundled helper implements this version. Earlier v0.1 material was a prose convention, not implemented storage; other schema versions are rejected rather than silently migrated.

## Commands and storage

`start`, `finish`, `note` and `report` accept `--root` and print UTF-8 JSON. `start` scans the selected scope into the immutable baseline. `report` scans current state without closing the run. `finish` saves the end observation; repeating it returns the original result. `note` appends a versioned statement about an existing regular file.

```text
<project>/.contextos/
  .gitignore                 '*' excludes local records from normal Git discovery
  runs/<run_id>/
    binding.json             actual local root path, not a portable identity
    run.json                 metadata, scope, exclusions and supplied native IDs
    before.json              original task-start observation
    after.json               first saved task-end observation, when available
    result.json              immutable closed result, when available
    notes/<note_id>.json      appended purpose/lifecycle statements
    .lock                    present during a write, or after a crash
```

Run and note IDs are UUID hex strings. Metadata records label, exact relative scopes, extra exclusion patterns, UTC observation times, optional conversation identifiers, `tracking_started_late`, and `fork_base_known: false`. Caller-supplied native identifiers are not authenticated by the helper.

The helper creates the ledger's own ignore file, without changing the top-level .gitignore. If an existing ledger ignore file lacks a literal `*` rule, it stops rather than overwriting it. Ignoring does not untrack previously committed records or prevent force-adding them. Runtime data is local; publication remains separate.

## Observation semantics

A snapshot contains `captured_at`, `algorithm: sha256`, regular-file `entries` with hash and size, `errors`, `excluded` and `coverage`. Coverage is `complete_within_scope` or `partial`. Even complete scoped snapshots do not reveal files created and deleted between observations, intermediate writes, omitted files or authorship. A scan is not a transactionally consistent filesystem snapshot.

Changes use `attribution: observed_only` and empty `evidence_refs`. Operations are created, modified, deleted or unknown. Before/after hashes identify observed bytes; they do not back up those bytes. Ambiguous renames appear as add/delete, without guessed resource identity.

Unreadable paths/directories prevent claims of creation/deletion beneath that uncertain observation. Errors remain visible even when neither snapshot has entries for that path. A missing entire workspace causes an error rather than reporting every file deleted. Ordinary deletion of an accessible scoped file is observable.

`result.json` stores closed state, end time, changes, coverage, empty checks and `task_success: null`. Closed means an end observation exists, not that development succeeded. A late start only covers the interval after tracking began.

## Notes and reports

Notes contain relative path, purpose, lifecycle, `source: agent_suggestion`, actual `basis_hash` and UTC recording time. Notes are file-level; directory inheritance is not implemented. `temporary` is a review hint, not deletion permission. Multiple notes are history, not automatically reconciled truths.

Reports show stored end changes for closed runs, or current start-to-now changes for open runs. They separately show current drift and note freshness (`current`, `stale`, `missing`, `unknown`). A stale note needs review; a hash change does not prove its purpose became wrong.

`--limit` defaults to 50, accepts 1–1000, and limits change/note/drift lists. Omitted counts accompany those lists; full observations remain on disk. Reports include errors, coverage and selected scope. Default exclusions are `.git`, `.contextos`, `.venv`, `venv`, `node_modules`, `__pycache__`, `dist`, `build`, `.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa*` and `id_ed25519*` (case-insensitive). Extra patterns match case-sensitively against relative paths or basenames. Git ignore rules are not implicitly imported.

## Recovery and boundaries

Writes use a per-run exclusive lock and temporary-file replacement. Separate runs have separate directories; project files remain shared. After a crash, verify its writer is inactive before manually removing a stale `.lock`. A saved after.json is reused after interrupted finalization. Missing/corrupt baseline or metadata is an error, not replaced by a new snapshot. A new run can start independently.

Scopes reject traversal and absolute/drive paths. Linked and Windows reparse paths are rejected or reported as gaps; the helper does not intentionally traverse symlinks/junctions. Reopened records must match the same resolved root. Rebinding, malicious concurrent filesystem replacement, access-policy enforcement and full audit guarantees are outside this helper's scope. Use the host's normal permissions and sandbox.

## Runtime compatibility

Harness is unnecessary for helper execution and synthetic tests. Real DSH/Synapse integration still needs pinned versions, verified Skill loading, native identifiers and fork behavior. This format defines no DSH hook names or HTTP API, and does not attach anything to the Synapse canvas.
