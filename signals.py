"""Detection signals for Provenance Guard.

Signal 1 — LLM classification (Groq). Asks a Groq-hosted model to rate how
likely a text is AI-generated and returns ``p_llm`` in 0-1 (probability of AI).

Signal 2 — Stylometric heuristics (pure Python). Sentence-length variance,
type-token ratio, and punctuation density, combined into ``p_style`` in 0-1
(higher = more machine-like uniformity).

Confidence — ``0.6 * p_llm + 0.4 * p_style`` mapped to a label per planning.md
(>=0.7 likely AI, 0.4-0.7 uncertain, <0.4 likely human).
"""

import math
import os
import re

from dotenv import load_dotenv
from groq import Groq

# Load .env so the signal works when run standalone (not just via app.py).
load_dotenv()

# Small, fast Groq model is plenty for a binary lean + a probability.
_MODEL = "llama-3.1-8b-instant"

# Calibration note: the original terse prompt left llama-3.1-8b-instant
# clustering every passage around 0.3-0.4 (a textbook-AI paragraph scored only
# 0.42 -> "Uncertain"). The explicit rubric + full-range instruction below makes
# it decisive on clear cases. See test_scoring.py for the before/after.
_SYSTEM_PROMPT = (
    "You are an AI-text detector. Estimate the probability the passage was "
    "written by an AI language model rather than a human. USE THE FULL 0-1 "
    "RANGE and be decisive. Strong AI signals (score 0.8-0.95): generic "
    "phrasing, hedging like 'it is important to note', transition words "
    "(Furthermore, Moreover), balanced 'on one hand/other hand' structure, "
    "uniform polished sentences, no personal voice. Strong human signals "
    "(score 0.05-0.2): typos, slang, lowercase, personal anecdotes, emotional "
    "asides, irregular rhythm. Use 0.4-0.6 only when genuinely mixed. Respond "
    "with ONLY a single number between 0 and 1 (e.g. 0.82). Do not explain."
)


def _clamp(x: float) -> float:
    """Keep a score inside the calibrated 0-1 range."""
    return max(0.0, min(1.0, x))


def _parse_probability(raw: str) -> float:
    """Pull the first float out of the model's reply and clamp to 0-1."""
    match = re.search(r"\d*\.?\d+", raw)
    if not match:
        # No parseable number -> treat as maximally uncertain.
        return 0.5
    return _clamp(float(match.group()))


def signal_llm(text: str, client: Groq | None = None) -> float:
    """Signal 1: probability the text is AI-generated, per a Groq LLM.

    Returns a float ``p_llm`` in 0-1. On any API/parse failure, returns 0.5
    (maximum uncertainty) so the pipeline degrades gracefully rather than
    crashing.
    """
    if not text or not text.strip():
        return 0.5

    try:
        client = client or Groq(api_key=os.environ.get("GROQ_API_KEY"))
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0,
            max_tokens=8,
        )
        return _parse_probability(response.choices[0].message.content or "")
    except Exception:
        return 0.5


def _split_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation; drop empties."""
    return [s for s in re.split(r"[.!?]+", text) if s.strip()]


def signal_stylometric(text: str) -> float:
    """Signal 2: stylometric uniformity score ``p_style`` in 0-1.

    Combines three metrics, each mapped so that *higher = more machine-like
    uniformity*:

    * **Sentence-length uniformity** — humans are "bursty" (high variance in
      words/sentence); AI is even. Uses coefficient of variation (std/mean);
      low CV -> high uniformity.
    * **Lexical repetition** — low type-token ratio (few unique words relative
      to total) reads as more uniform/repetitive.
    * **Punctuation regularity** — closeness to a typical, moderate punctuation
      density; extreme sparsity or density looks less machine-like.

    The three are averaged into a single 0-1 score. Returns 0.5 (maximally
    uncertain) for empty/degenerate input, matching Signal 1's failure mode.
    """
    words = re.findall(r"[A-Za-z']+", text)
    if len(words) < 2:
        return 0.5

    # 1. Sentence-length uniformity via coefficient of variation.
    sentences = _split_sentences(text)
    lengths = [len(re.findall(r"[A-Za-z']+", s)) for s in sentences]
    lengths = [n for n in lengths if n > 0]
    if len(lengths) >= 2:
        mean = sum(lengths) / len(lengths)
        var = sum((n - mean) ** 2 for n in lengths) / len(lengths)
        cv = math.sqrt(var) / mean if mean else 0.0
        # CV ~0 -> perfectly uniform (1.0); CV >=1 -> very bursty (0.0).
        sent_uniformity = _clamp(1.0 - cv)
    else:
        # Single sentence: no variance signal, stay neutral.
        sent_uniformity = 0.5

    # 2. Lexical repetition: low type-token ratio -> high uniformity.
    ttr = len(set(w.lower() for w in words)) / len(words)
    lexical_uniformity = _clamp(1.0 - ttr)

    # 3. Punctuation regularity: distance from a moderate target density.
    punct = len(re.findall(r"[,;:\-—()\"']", text))
    density = punct / len(words)
    # Target ~0.12 punctuation marks per word; penalize deviation.
    punct_regularity = _clamp(1.0 - abs(density - 0.12) / 0.12)

    return _clamp((sent_uniformity + lexical_uniformity + punct_regularity) / 3)


def combine_confidence(p_llm: float, p_style: float) -> float:
    """Weighted average per planning.md: 0.6 * p_llm + 0.4 * p_style."""
    return _clamp(0.6 * _clamp(p_llm) + 0.4 * _clamp(p_style))


def make_label(confidence: float) -> str:
    """Map a combined confidence to a transparency category (planning.md).

    >=0.7 -> "Likely AI-generated"; 0.4-0.7 -> "Uncertain"; <0.4 -> "Likely
    human-written".
    """
    if confidence >= 0.7:
        return "Likely AI-generated"
    if confidence >= 0.4:
        return "Uncertain"
    return "Likely human-written"


if __name__ == "__main__":
    # Direct test of both signals on the SAME inputs (per M4 verification):
    # do the semantic (LLM) and structural (stylometric) signals agree?
    samples = [
        "I went to the store and the cat was there, weird day honestly lol.",
        "Furthermore, the implementation leverages a robust framework to "
        "facilitate seamless integration across multiple domains.",
    ]
    for s in samples:
        p_llm = signal_llm(s)
        p_style = signal_stylometric(s)
        conf = combine_confidence(p_llm, p_style)
        print(
            f"p_llm={p_llm:.2f}  p_style={p_style:.2f}  "
            f"confidence={conf:.2f}  [{make_label(conf)}]  |  {s[:50]}..."
        )
