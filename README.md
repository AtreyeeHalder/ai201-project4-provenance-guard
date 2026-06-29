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

