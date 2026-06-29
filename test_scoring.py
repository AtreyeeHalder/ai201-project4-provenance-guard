"""Calibration test for the scoring pipeline (M4 verification).

Runs 4 deliberately chosen inputs through both signals and the combined
confidence score, printing each signal SEPARATELY so a miscalibrated signal is
visible. Expected, per planning.md thresholds:
  confidence >= 0.7 -> Likely AI-generated
  0.4 <= confidence < 0.7 -> Uncertain
  confidence < 0.4 -> Likely human-written
"""

from signals import combine_confidence, make_label, signal_llm, signal_stylometric

CASES = [
    (
        "clearly AI (expect HIGH / Likely AI)",
        "Artificial intelligence represents a transformative paradigm shift in "
        "modern society. It is important to note that while the benefits of AI "
        "are numerous, it is equally essential to consider the ethical "
        "implications. Furthermore, stakeholders across various sectors must "
        "collaborate to ensure responsible deployment.",
    ),
    (
        "clearly human (expect LOW / Likely human)",
        "ok so i finally tried that new ramen place downtown and honestly? "
        "underwhelming. the broth was fine but they put WAY too much sodium in "
        "it and i was thirsty for like three hours after. my friend got the "
        "spicy version and said it was better. probably won't go back unless "
        "someone drags me there",
    ),
    (
        "borderline: formal human (may score mid-high)",
        "The relationship between monetary policy and asset price inflation has "
        "been extensively studied in the literature. Central banks face a "
        "fundamental tension between their mandate for price stability and the "
        "unintended consequences of prolonged low interest rates on equity and "
        "real estate valuations.",
    ),
    (
        "borderline: lightly edited AI (expect mid-range)",
        "I've been thinking a lot about remote work lately. There are genuine "
        "tradeoffs — flexibility and no commute on one side, isolation and "
        "blurred work-life boundaries on the other. Studies show productivity "
        "varies widely by individual and role type.",
    ),
]


def main() -> None:
    print(f"{'case':<46}{'p_llm':>7}{'p_style':>9}{'conf':>7}  label")
    print("-" * 90)
    for label, text in CASES:
        p_llm = signal_llm(text)
        p_style = signal_stylometric(text)
        conf = combine_confidence(p_llm, p_style)
        print(
            f"{label:<46}{p_llm:>7.2f}{p_style:>9.2f}{conf:>7.2f}  "
            f"{make_label(conf)}"
        )


if __name__ == "__main__":
    main()
