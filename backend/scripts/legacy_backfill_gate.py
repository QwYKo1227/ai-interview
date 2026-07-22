"""Validate deterministic zero/nonzero legacy-backfill rollout decisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Iterable


BACKFILL_SCHEMA = "ai-interview.legacy-upload-backfill"
PLAN_SCHEMA = "ai-interview.legacy-upload-plan"
RESULT_SCHEMA = "ai-interview.legacy-upload-result"
VERSION = 1


class LegacyBackfillGateError(ValueError):
    """Stable validation failure which never includes source payload values."""


def _candidate_keys(payload: dict) -> list[tuple[str, str, str]]:
    try:
        return sorted(
            (item["table"], item["tenant_id"], item["row_id"])
            for item in payload["items"]
        )
    except (KeyError, TypeError):
        raise LegacyBackfillGateError("invalid legacy candidate items") from None


def _validate_dry_payload(payload: dict, *, mode: str) -> int:
    try:
        counts = payload["counts"]
        candidates = counts["candidates"]
        pending = counts["pending"]
        errors = counts["errors"]
        valid = (
            payload["schema"] == BACKFILL_SCHEMA
            and payload["version"] == VERSION
            and payload["ok"] is True
            and payload["mode"] == mode
            and payload["dry_run"] is True
            and isinstance(candidates, int)
            and not isinstance(candidates, bool)
            and isinstance(pending, int)
            and not isinstance(pending, bool)
            and candidates >= 0
            and candidates == pending
            and errors == 0
            and len(payload["items"]) == candidates
            and all(item["status"] == "would_migrate" for item in payload["items"])
        )
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise LegacyBackfillGateError("invalid legacy dry-run payload")
    _candidate_keys(payload)
    return pending


def plan_legacy_backfill(inventory: dict, dry_run: dict) -> dict:
    inventory_pending = _validate_dry_payload(inventory, mode="inventory")
    dry_run_pending = _validate_dry_payload(dry_run, mode="migrate")
    if inventory_pending != dry_run_pending:
        raise LegacyBackfillGateError("legacy pending counts changed during planning")
    if _candidate_keys(inventory) != _candidate_keys(dry_run):
        raise LegacyBackfillGateError("legacy candidates changed during planning")
    return {
        "schema": PLAN_SCHEMA,
        "version": VERSION,
        "ok": True,
        "action": "migrate" if inventory_pending else "skip",
        "pending": inventory_pending,
    }


def _validate_plan(plan: dict) -> tuple[str, int]:
    try:
        action = plan["action"]
        pending = plan["pending"]
        valid = (
            plan["schema"] == PLAN_SCHEMA
            and plan["version"] == VERSION
            and plan["ok"] is True
            and action in {"skip", "migrate"}
            and isinstance(pending, int)
            and not isinstance(pending, bool)
            and pending >= 0
            and ((pending == 0) == (action == "skip"))
        )
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise LegacyBackfillGateError("invalid legacy backfill plan")
    return action, pending


def finalize_legacy_backfill(plan: dict, migration: dict | None = None) -> dict:
    action, pending = _validate_plan(plan)
    if action == "skip":
        if migration is not None:
            raise LegacyBackfillGateError("zero-pending plan must skip migration")
        migrated = 0
    else:
        if migration is None:
            raise LegacyBackfillGateError("positive-pending plan requires migration")
        try:
            counts = migration["counts"]
            migrated = sum(
                item["status"] == "migrated" for item in migration["items"]
            )
            valid = (
                migration["schema"] == BACKFILL_SCHEMA
                and migration["version"] == VERSION
                and migration["ok"] is True
                and migration["mode"] == "migrate"
                and migration["dry_run"] is False
                and counts["candidates"] == pending
                and counts["pending"] == 0
                and counts["errors"] == 0
                and len(migration["items"]) == pending
                and migrated == pending
                and all(
                    item["status"] == "migrated" for item in migration["items"]
                )
            )
        except (KeyError, TypeError):
            valid = False
        if not valid:
            raise LegacyBackfillGateError("migration does not match legacy plan")
    return {
        "schema": RESULT_SCHEMA,
        "version": VERSION,
        "ok": True,
        "action": action,
        "pending": pending,
        "stored_files_increase": migrated,
    }


def run_cli(argv: Iterable[str] | None = None, *, stdout=None) -> int:
    parser = argparse.ArgumentParser(description="Gate a legacy backfill rollout")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--inventory", required=True, type=Path)
    plan_parser.add_argument("--dry-run", required=True, type=Path)
    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--plan", required=True, type=Path)
    finalize_parser.add_argument("--migration", type=Path)
    args = parser.parse_args(argv)
    stdout = sys.stdout if stdout is None else stdout
    try:
        if args.command == "plan":
            payload = plan_legacy_backfill(
                json.loads(args.inventory.read_text(encoding="utf-8")),
                json.loads(args.dry_run.read_text(encoding="utf-8")),
            )
        else:
            migration = (
                json.loads(args.migration.read_text(encoding="utf-8"))
                if args.migration
                else None
            )
            payload = finalize_legacy_backfill(
                json.loads(args.plan.read_text(encoding="utf-8")),
                migration,
            )
    except Exception:
        payload = {
            "schema": "ai-interview.legacy-upload-gate-error",
            "version": VERSION,
            "ok": False,
            "error": "legacy backfill gate failed",
        }
    print(json.dumps(payload, sort_keys=True), file=stdout)
    return 0 if payload["ok"] else 1


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
