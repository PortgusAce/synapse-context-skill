#!/usr/bin/env python3
"""Task-scoped file observations. Python 3.10+, standard library only."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import uuid

VERSION = "0.2"
EXCLUDED_DIRS = {".git", ".contextos", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
EXCLUDED_FILES = (".env", ".env.*", "*.pem", "*.key", "id_rsa*", "id_ed25519*")


def now():
    return datetime.now(timezone.utc).isoformat()


def relative(value):
    value = str(value).replace("\\", "/")
    p = PurePosixPath(value)
    if not value or p.is_absolute() or ".." in p.parts or ":" in value:
        raise ValueError("Expected a relative path without '..', drive or stream syntax")
    return p.as_posix()


def linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def beneath(root, name):
    path = root
    for part in PurePosixPath(relative(name)).parts:
        path = path / part
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if linked(info):
            raise ValueError("Linked/reparse paths are not supported: " + name)
    return path


def excluded(name, patterns):
    parts = PurePosixPath(name).parts
    if not parts:
        return False
    return (any(part.casefold() in EXCLUDED_DIRS for part in parts)
            or any(fnmatch.fnmatchcase(parts[-1].casefold(), pat) for pat in EXCLUDED_FILES)
            or any(fnmatch.fnmatchcase(name, pat) or fnmatch.fnmatchcase(parts[-1], pat) for pat in patterns))


def signature(info):
    # Windows Python can expose different ctime semantics via stat and fstat.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def fingerprint(path):
    first = path.lstat()
    if linked(first) or not stat.S_ISREG(first.st_mode):
        raise ValueError("Not a regular, unlinked file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    digest = hashlib.sha256()
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if signature(first) != signature(opened):
            raise ValueError("File changed before hashing")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        last = os.fstat(stream.fileno())
    if signature(first) != signature(last) or signature(first) != signature(path.lstat()):
        raise ValueError("File changed while hashing")
    return {"sha256": digest.hexdigest(), "size": first.st_size}


def snapshot(root, scopes, patterns):
    entries, errors, omitted, visited = {}, [], [], set()

    def visit(name):
        if name in visited:
            return
        visited.add(name)
        if excluded(name, patterns):
            omitted.append(name)
            return
        try:
            path = beneath(root, name)
            try:
                info = path.lstat()
            except FileNotFoundError:
                return  # Absence at this observation, not historical deletion.
            if stat.S_ISDIR(info.st_mode):
                children = sorted(path.iterdir(), key=lambda p: p.name)
                for child in children:
                    visit(child.relative_to(root).as_posix())
            elif stat.S_ISREG(info.st_mode):
                entries[name] = fingerprint(path)
            else:
                errors.append({"path": name, "reason": "unsupported_file_type"})
        except (OSError, ValueError) as exc:
            # Avoid machine paths or OS-localized error text in shareable records.
            errors.append({"path": name, "reason": type(exc).__name__})

    for scope in scopes:
        visit(scope)
    return {"captured_at": now(), "algorithm": "sha256", "entries": entries,
            "errors": errors, "excluded": sorted(omitted),
            "coverage": "partial" if errors else "complete_within_scope"}


def uncertain(name, snap):
    for item in snap["errors"]:
        prefix = item["path"]
        if prefix == "." or name == prefix or name.startswith(prefix + "/"):
            return True
    return False


def compare(before, after):
    changes = []
    for name in sorted(before["entries"].keys() | after["entries"].keys()):
        old, new = before["entries"].get(name), after["entries"].get(name)
        if uncertain(name, before) or uncertain(name, after):
            operation = "unknown"
        elif old is None:
            operation = "created"
        elif new is None:
            operation = "deleted"
        elif old["sha256"] != new["sha256"]:
            operation = "modified"
        else:
            continue
        changes.append({"path": name, "operation": operation,
                        "before_hash": old["sha256"] if old else None,
                        "after_hash": new["sha256"] if new else None,
                        "attribution": "observed_only", "evidence_refs": []})
    return changes


def write_json(path, value):
    if path.exists():
        raise ValueError("Refusing to overwrite an existing record")
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    if linked(path.lstat()) or not path.is_file():
        raise ValueError("Record must be an unlinked regular file")
    return json.loads(path.read_text(encoding="utf-8"))


def workspace(value):
    root = Path(value).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Workspace must be an existing directory")
    return root


def storage(root):
    store = beneath(root, ".contextos/runs")
    store.mkdir(parents=True, exist_ok=True)
    ignore = beneath(root, ".contextos/.gitignore")
    if not ignore.exists():
        try:
            with ignore.open("x", encoding="utf-8") as stream:
                stream.write("# Local task observations; do not publish.\n*\n")
        except FileExistsError:
            pass
    if "*" not in ignore.read_text(encoding="utf-8").splitlines():
        raise ValueError("Existing .contextos/.gitignore needs a '*' rule; not overwritten")
    return store


def load_run(root, run_id):
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Invalid run ID")
    directory = beneath(root, ".contextos/runs/" + run_id)
    record = read_json(directory / "run.json")
    binding = read_json(directory / "binding.json")
    if binding["root"] != str(root):
        raise ValueError("Workspace binding changed; automatic rebinding is not supported")
    if record["schema_version"] != VERSION or record["run_id"] != run_id:
        raise ValueError("Unsupported or mismatched run record")
    return directory, record


@contextmanager
def locked(directory):
    path = directory / ".lock"
    try:
        stream = path.open("x", encoding="utf-8")
    except FileExistsError:
        raise ValueError("Run is locked; verify no writer is active before manually removing a stale .lock") from None
    try:
        with stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        path.unlink()


def start(root, scopes, patterns=(), label="", conversation=None, late=False):
    scopes = sorted(set(relative(value) for value in scopes))
    if not scopes or any(excluded(value, patterns) for value in scopes):
        raise ValueError("Supply non-excluded relative file/directory scopes")
    # Validate linked scopes before creating ledger files.
    for scope in scopes:
        beneath(root, scope)
    run_id = uuid.uuid4().hex
    directory = storage(root) / run_id
    directory.mkdir()
    record = {"schema_version": VERSION, "run_id": run_id, "label": label,
              "scope": scopes, "exclude_patterns": list(patterns),
              "conversation": conversation or {key: None for key in ("session_id", "turn_id", "parent_session_id", "fork_anchor")},
              "fork_base_known": False, "tracking_started_late": late, "started_at": now()}
    write_json(directory / "binding.json", {"root": str(root)})
    write_json(directory / "before.json", snapshot(root, scopes, patterns))
    write_json(directory / "run.json", record)
    return {"run_id": run_id, "record_dir": str(directory), "scope": scopes,
            "coverage": read_json(directory / "before.json")["coverage"], "tracking_started_late": late}


def finish(root, run_id):
    directory, record = load_run(root, run_id)
    with locked(directory):
        result_path = directory / "result.json"
        if result_path.exists():
            return read_json(result_path)
        before = read_json(directory / "before.json")  # Fail if baseline is missing.
        after_path = directory / "after.json"
        if not after_path.exists():
            write_json(after_path, snapshot(root, record["scope"], record["exclude_patterns"]))
        after = read_json(after_path)
        result = {"schema_version": VERSION, "run_id": run_id, "state": "closed",
                  "ended_at": after["captured_at"], "changes": compare(before, after),
                  "coverage": "partial" if before["errors"] or after["errors"] else "complete_within_scope",
                  "checks": [], "task_success": None}
        write_json(result_path, result)
        return result


def note(root, run_id, path, purpose, lifecycle):
    directory, record = load_run(root, run_id)
    name = relative(path)
    if not purpose.strip():
        raise ValueError("Purpose must not be blank")
    if lifecycle not in ("active", "temporary", "superseded", "unknown"):
        raise ValueError("Unsupported lifecycle")
    if not any(scope == "." or name == scope or name.startswith(scope + "/") for scope in record["scope"]):
        raise ValueError("Note path is outside this run's scope")
    if excluded(name, record["exclude_patterns"]):
        raise ValueError("Note path is excluded")
    info = fingerprint(beneath(root, name))
    value = {"path": name, "purpose": purpose, "lifecycle": lifecycle,
             "source": "agent_suggestion", "basis_hash": info["sha256"], "recorded_at": now()}
    with locked(directory):
        notes = beneath(root, str((directory / "notes").relative_to(root)))
        notes.mkdir(exist_ok=True)
        write_json(notes / (uuid.uuid4().hex + ".json"), value)
    return value


def report(root, run_id, limit=50):
    directory, record = load_run(root, run_id)
    before = read_json(directory / "before.json")
    current = snapshot(root, record["scope"], record["exclude_patterns"])
    result_path = directory / "result.json"
    result = read_json(result_path) if result_path.exists() else None
    changes = result["changes"] if result else compare(before, current)
    basis = read_json(directory / "after.json") if result else before
    notes = []
    notes_dir = beneath(root, str((directory / "notes").relative_to(root)))
    if notes_dir.exists():
        for path in sorted(notes_dir.glob("*.json")):
            item = read_json(path)
            actual = current["entries"].get(item["path"])
            item["freshness"] = ("unknown" if uncertain(item["path"], current) else
                                 "missing" if actual is None else
                                 "current" if actual["sha256"] == item["basis_hash"] else "stale")
            notes.append(item)
    notes.sort(key=lambda item: item["recorded_at"], reverse=True)
    counts = {op: sum(item["operation"] == op for item in changes) for op in ("created", "modified", "deleted", "unknown")}
    drift = compare(basis, current)
    return {"schema_version": VERSION, "run_id": run_id, "label": record["label"],
            "state": "closed" if result else "open", "conversation": record["conversation"],
            "scope": record["scope"], "tracking_started_late": record["tracking_started_late"],
            "fork_base_known": False, "counts": counts, "changes": changes[:limit],
            "coverage": {"baseline": before["coverage"], "current": current["coverage"],
                         "finished": result["coverage"] if result else None},
            "changes_omitted": max(0, len(changes) - limit), "notes": notes[:limit],
            "notes_omitted": max(0, len(notes) - limit),
            "current_drift": drift[:limit], "current_drift_omitted": max(0, len(drift) - limit),
            "baseline_errors": before["errors"], "current_errors": current["errors"],
            "observation_errors": read_json(directory / "after.json")["errors"] if result else current["errors"],
            "excluded": current["excluded"][:limit], "record_dir": str(directory)}


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("start", "finish", "note", "report"):
        p = sub.add_parser(command)
        p.add_argument("--root", required=True, help="Existing project directory")
        if command != "start":
            p.add_argument("--run", required=True, help="Run ID returned by start")
        if command == "start":
            p.add_argument("--include", action="append", required=True, help="Relative file/directory, repeatable; no glob")
            p.add_argument("--exclude", action="append", default=[], help="Additional case-sensitive glob, repeatable")
            p.add_argument("--label", default="")
            p.add_argument("--late", action="store_true", help="Earlier task changes were not captured")
            for field in ("session-id", "turn-id", "parent-session-id", "fork-anchor"):
                p.add_argument("--" + field)
        elif command == "note":
            p.add_argument("--path", required=True)
            p.add_argument("--purpose", required=True)
            p.add_argument("--lifecycle", choices=("active", "temporary", "superseded", "unknown"), default="unknown")
        elif command == "report":
            p.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)
    try:
        root = workspace(args.root)
        if args.command == "start":
            conversation = {field: getattr(args, field) for field in ("session_id", "turn_id", "parent_session_id", "fork_anchor")}
            output = start(root, args.include, args.exclude, args.label, conversation, args.late)
        elif args.command == "finish":
            result = finish(root, args.run)
            output = {key: result[key] for key in ("run_id", "state", "coverage", "task_success")}
            output["change_count"] = len(result["changes"])
        elif args.command == "note":
            output = note(root, args.run, args.path, args.purpose, args.lifecycle)
        else:
            if not 1 <= args.limit <= 1000:
                raise ValueError("Limit must be between 1 and 1000")
            output = report(root, args.run, args.limit)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
