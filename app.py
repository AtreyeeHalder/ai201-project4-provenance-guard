"""Provenance Guard — Flask app.

Submission flow (M3 stage): POST /submit -> Signal 1 (LLM) -> [Signal 2,
confidence scoring, label, audit log fully wired in M4/M5] -> response.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from signals import combine_confidence, make_label, signal_llm, signal_stylometric

load_dotenv()

app = Flask(__name__)

# Rate limiting keyed by client IP. In-memory storage is fine for local/dev
# (single process); swap storage_uri for Redis in production. See README for
# the rationale behind the per-route limits.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

# In-memory store + a structured, append-only audit log on disk (JSON Lines).
SUBMISSIONS: dict[str, dict] = {}
LOG_FILE = Path(__file__).with_name("audit_log.jsonl")


def write_log(entry: dict) -> None:
    """Append one structured entry to the audit log (one JSON object per line)."""
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def get_log(limit: int = 50) -> list[dict]:
    """Return the most recent audit log entries, newest last."""
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[-limit:] if line.strip()]


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": get_log()})


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    """Accept text + creator_id, run Signal 1, return attribution + placeholders.

    M3 stage: runs Signal 1 (Groq LLM) only. The combined confidence score and
    the transparency label are placeholders until Signal 2 and the scoring
    logic land in M4/M5.
    """
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    creator_id = (data.get("creator_id") or "").strip()

    if not text:
        return jsonify({"error": "Field 'text' is required and cannot be empty."}), 400
    if not creator_id:
        return jsonify({"error": "Field 'creator_id' is required and cannot be empty."}), 400

    # Signal 1 — LLM classification (Groq). Returns p_llm in 0-1 (prob. of AI).
    p_llm = signal_llm(text)
    # Signal 2 — stylometric uniformity (pure Python). Returns p_style in 0-1.
    p_style = signal_stylometric(text)
    attribution = {"signal": "llm_groq+stylometric", "p_llm": p_llm, "p_style": p_style}

    # Confidence scoring per planning.md: 0.6 * p_llm + 0.4 * p_style.
    confidence = combine_confidence(p_llm, p_style)
    label = make_label(confidence)

    content_id = str(uuid.uuid4())
    SUBMISSIONS[content_id] = {
        "content_id": content_id,
        "creator_id": creator_id,
        "text": text,
        "attribution": attribution,
        "confidence": confidence,
        "label": label,
        "status": "classified",
    }

    # Structured audit log entry — extended with p_style/confidence in M4.
    write_log(
        {
            "content_id": content_id,
            "creator_id": creator_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attribution": label,  # transparency category
            "confidence": confidence,  # combined score (0.6*p_llm + 0.4*p_style)
            "llm_score": p_llm,  # signal 1 score
            "style_score": p_style,  # signal 2 score
            "status": "classified",
        }
    )

    return jsonify(
        {
            "content_id": content_id,
            "creator_id": creator_id,
            "attribution": attribution,
            "confidence": confidence,
            "label": label,
            "status": "classified",
        }
    )


@app.route("/appeal", methods=["POST"])
def appeal():
    """Accept an appeal for a prior classification (planning.md appeals flow).

    Looks up the submission by content_id, flips its status to "under review",
    and logs the appeal alongside the original classification decision. Does
    not run automated re-classification — a human reviewer handles the queue.
    """
    data = request.get_json(silent=True) or {}
    content_id = (data.get("content_id") or "").strip()
    creator_reasoning = (data.get("creator_reasoning") or "").strip()

    if not content_id:
        return jsonify({"error": "Field 'content_id' is required and cannot be empty."}), 400
    if not creator_reasoning:
        return jsonify({"error": "Field 'creator_reasoning' is required and cannot be empty."}), 400

    submission = SUBMISSIONS.get(content_id)
    if submission is None:
        return jsonify({"error": f"No submission found for content_id '{content_id}'."}), 404

    # Status update: classified -> under review.
    submission["status"] = "under review"

    # Log the appeal alongside the original classification decision.
    write_log(
        {
            "content_id": content_id,
            "creator_id": submission["creator_id"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "appeal",
            "creator_reasoning": creator_reasoning,
            "original_label": submission["label"],
            "original_confidence": submission["confidence"],
            "status": "under review",
        }
    )

    return jsonify(
        {
            "content_id": content_id,
            "status": "under review",
            "message": "Appeal received and queued for human review.",
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
