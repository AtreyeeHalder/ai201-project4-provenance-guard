# Project 4 — Provenance Guard

## Rate Limiting

The `/submit` endpoint is rate-limited per client IP (Flask-Limiter, in-memory
storage) with **`10 per minute; 100 per day`**.

**Reasoning.** A genuine writer submitting their own work checks a handful of
drafts at a time — 10/minute leaves ample headroom for revising and re-checking
a piece without ever hitting the wall, while still cutting off a script that
would otherwise fire hundreds of requests per minute. The 100/day ceiling caps
sustained automated abuse (and the cost of the per-submission Groq call) at a
level a human reviewer would essentially never reach in normal use. The limits
apply only to `/submit`; read-only routes (`/health`, `/log`) and `/appeal` are
unthrottled.

**Verification.** Sending 12 rapid `POST /submit` requests shows the first 10
accepted and the rest rejected with `429 Too Many Requests`:

```
200
200
200
200
200
200
200
200
200
200
429
429
```

## Audit Log

Every classification appends one structured JSON line to `audit_log.jsonl`
capturing the timestamp, content ID, attribution label, combined confidence,
both individual signal scores (`llm_score`, `style_score`), and status; appeals
are recorded as separate `event: "appeal"` entries. Sample entries:

```json
{"content_id": "c6feb1e1-0ea2-4c78-830e-916f1cfe665f", "creator_id": "u1", "timestamp": "2026-06-29T19:03:06.890594+00:00", "attribution": "\u26a0\ufe0f Likely AI-generated (confidence 0.7+). This text shows strong signals of automated generation. This is an estimate, not proof; the user may appeal.", "confidence": 0.7041367521367522, "llm_score": 0.92, "style_score": 0.3803418803418803, "status": "classified"}
{"content_id": "33e39b76-7786-45b1-8c0f-b58053bb6ec1", "creator_id": "u2", "timestamp": "2026-06-29T19:03:37.818740+00:00", "attribution": "\u2713 Likely human-written (confidence under 0.4). This text shows signals consistent with human writing. This is an estimate, not proof.", "confidence": 0.14039506172839508, "llm_score": 0.02, "style_score": 0.32098765432098764, "status": "classified"}
{"content_id": "832cd85f-af65-45dd-bd49-6839956fbc5f", "creator_id": "u3", "timestamp": "2026-06-29T19:03:47.641726+00:00", "attribution": "\u2753 Uncertain (confidence 0.4\u20130.7). Our signals disagree or are weak; we cannot confidently classify this text. Treat the result with caution.", "confidence": 0.6347276972864604, "llm_score": 0.92, "style_score": 0.206819243216151, "status": "classified"}
```

