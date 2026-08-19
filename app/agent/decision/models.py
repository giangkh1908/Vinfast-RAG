"""P0 schema models — RetrievedChunk, DisplayedCitation, DecisionLog + in-memory LogStore."""

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.agent.decision.version_utils import _get_build_version, _get_data_snapshot_id

logger = logging.getLogger("bds.decision")


@dataclass
class RetrievedChunk:
    rank: int = 0
    chunk_id: str = ""
    source_id: str = ""
    source_title: str = ""
    source_url: str = ""
    document_name: str = ""
    page: str = ""
    section: str = ""
    content: str = ""
    vehicle_model: str = ""
    vehicle_version: str = ""
    topic: str = ""
    approval_status: str = "approved"
    market: str = "Vietnam"
    language: str = "vi"
    retrieval_score: float = 0.0


@dataclass
class DisplayedCitation:
    citation_id: str = ""
    display_text: str = ""
    source_id: str = ""
    chunk_ids: list[str] = field(default_factory=list)
    source_url: str = ""
    document_name: str = ""
    page: str = ""
    section: str = ""


@dataclass
class DecisionLog:
    # §4.1 Request & version identity
    schema_version: str = "1.0"
    request_id: str = ""
    timestamp: str = ""
    run_id: str = ""
    test_id: str = ""
    build_version: str = ""
    prompt_version: str = ""
    data_snapshot_id: str = ""
    environment: str = "production"
    retrieval_config_version: str = ""
    conversation_id: str = ""
    turn_index: int = 0
    previous_request_id: str = ""

    # §4.2 Input & detected context
    user_query: str = ""
    detected_vehicle_model: str = "unknown"
    detected_vehicle_version: str = "unknown"
    detected_topic: str = "unknown"
    decision: str = ""
    reason_code: str = ""

    # §4.3 Retrieval & evidence
    retrieval_status: str = "not_run"
    retrieved_chunks: list[dict] = field(default_factory=list)
    retrieval_query: str = ""
    requested_top_k: int = 5
    evidence_assessment: str = ""

    # §4.4 Answer & citation
    displayed_answer: str = ""
    displayed_citations: list[dict] = field(default_factory=list)

    # §4.5 Latency & error
    error_stage: str = ""
    error_type: str = ""
    error_message: str = ""
    latency_total_ms: float = 0.0
    latency_retrieval_ms: float = 0.0
    latency_generation_ms: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        # Convert empty strings to null for nullable fields
        nullable_fields = [
            "conversation_id",
            "turn_index",
            "previous_request_id",
            "error_stage",
            "error_type",
            "error_message",
            "test_id",
            "retrieval_config_version",
        ]
        for f in nullable_fields:
            if d.get(f) == "" or d.get(f) == 0:
                d[f] = None
        return d


# ── Log Store (in-memory, exportable) ──────────────────────────────────────
class LogStore:
    """In-memory store for decision logs. Export to JSONL."""

    def __init__(self):
        self._logs: list[dict] = []
        self._run_id = ""
        self._run_timestamp = ""

    def start_run(self) -> str:
        self._run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self._run_timestamp = datetime.now(UTC).isoformat()
        return self._run_id

    def add(self, log: DecisionLog) -> None:
        if not self._run_id:
            self.start_run()
        log.run_id = self._run_id
        if not log.build_version:
            log.build_version = _get_build_version()
        if not log.data_snapshot_id:
            log.data_snapshot_id = _get_data_snapshot_id()
        self._logs.append(log.to_dict())

    def get_all(self) -> list[dict]:
        return list(self._logs)

    def get_by_run(self, run_id: str) -> list[dict]:
        return [log_item for log_item in self._logs if log_item.get("run_id") == run_id]

    def export_jsonl(self, path: str | Path) -> int:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for log in self._logs:
                f.write(json.dumps(log, ensure_ascii=False) + "\n")
        return len(self._logs)

    def clear(self):
        self._logs.clear()


log_store = LogStore()
