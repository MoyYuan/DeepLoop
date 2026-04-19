from __future__ import annotations

RUNTIME_STATE_FILE = "mission_runtime_state.json"
RUNTIME_HISTORY_FILE = "mission_runtime_history.jsonl"
RUNTIME_SUMMARY_JSON_FILE = "mission_runtime_summary.json"
RUNTIME_SUMMARY_MD_FILE = "mission_runtime_summary.md"

TERMINAL_BRANCH_STATUSES = {"completed", "blocked", "abandoned"}
ACTIVE_BRANCH_STATUSES = {"planned", "active", "recovery-active", "replication-active", "critique-ready", "report-ready"}


__all__ = [
    "ACTIVE_BRANCH_STATUSES",
    "RUNTIME_HISTORY_FILE",
    "RUNTIME_STATE_FILE",
    "RUNTIME_SUMMARY_JSON_FILE",
    "RUNTIME_SUMMARY_MD_FILE",
    "TERMINAL_BRANCH_STATUSES",
]
