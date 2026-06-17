#!/usr/bin/env python3
"""
Token estimator for the scraped EUEE question set.

Parses the latest euee_*.json with orjson and counts tokens across all
questions so we can size the Gemini enrichment job against the free-tier
limits BEFORE making any API calls.

Counts:
  - per-question CONTENT tokens (question text + every choice's text)
  - image counts (body + choice images) -> estimated image-token cost
  - projected INPUT tokens per Gemini call (content + prompt scaffold +
    retrieved vector-DB context) and projected OUTPUT tokens (explanations)

Token counts use tiktoken's cl100k_base as an approximation; Gemini uses a
different tokenizer, so treat these as indicative (usually within ~10-15%).
"""

import glob
import os
import sys

import orjson
import tiktoken

# ── Tunable assumptions for the projection (not the raw content count) ─────────
PROMPT_SCAFFOLD_TOKENS = 900    # role + instructions + output JSON schema, per call
CONTEXT_CHUNKS = 5              # top-k curriculum chunks fed to Gemini for topic/grade/unit
TOKENS_PER_CHUNK = 220         # avg tokens per retrieved Milvus chunk (~nomic chunk size)
IMAGE_TOKENS_EACH = 258        # Gemini low-res image baseline (<=384px); larger images tile higher
OUTPUT_TOKENS_PER_Q = 550      # explanations + incorrect_explanations + topic + answer

enc = tiktoken.get_encoding("cl100k_base")


def ntok(text: str) -> int:
    return len(enc.encode(text)) if text else 0


def find_latest_json() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    for root in (
        os.path.join(here, "..", "..", "..", "euee_output"),   # project root
        os.path.join(here, "..", "..", "euee_output"),         # backend/
    ):
        candidates += glob.glob(os.path.join(root, "euee_*.json"))
    if not candidates:
        sys.exit("No euee_*.json found in euee_output/")
    return max(candidates, key=os.path.getmtime)


def question_content_tokens(q: dict) -> tuple[int, int]:
    """Return (text_tokens, image_count) for one question."""
    parts = [q.get("Question") or ""]
    images = 0
    if q.get("Question_image"):
        images += 1
    for c in q.get("Choices", []):
        if c.get("text"):
            parts.append(c["text"])
        if c.get("image"):
            images += 1
    return ntok(" ".join(parts)), images


def fmt(n: int) -> str:
    return f"{n:,}"


def main() -> None:
    path = find_latest_json()
    with open(path, "rb") as f:
        exams = orjson.loads(f.read())

    by_subject: dict[str, dict] = {}
    total_q = total_content = total_images = 0

    for exam in exams:
        subj = exam.get("Subject", "?")
        bucket = by_subject.setdefault(subj, {"q": 0, "content": 0, "images": 0})
        for q in exam.get("Questions", []):
            c_tok, imgs = question_content_tokens(q)
            bucket["q"] += 1
            bucket["content"] += c_tok
            bucket["images"] += imgs
            total_q += 1
            total_content += c_tok
            total_images += imgs

    print(f"Source: {os.path.relpath(path)}\n")
    print(f"{'Subject':<48}{'Qs':>6}{'ContentTok':>13}{'Imgs':>7}{'Avg/Q':>8}")
    print("-" * 82)
    for subj in sorted(by_subject, key=lambda s: -by_subject[s]["content"]):
        b = by_subject[subj]
        avg = b["content"] // b["q"] if b["q"] else 0
        print(f"{subj[:47]:<48}{b['q']:>6}{fmt(b['content']):>13}{b['images']:>7}{avg:>8}")
    print("-" * 82)
    print(f"{'TOTAL':<48}{total_q:>6}{fmt(total_content):>13}{total_images:>7}"
          f"{(total_content // total_q if total_q else 0):>8}\n")

    # ── Projection against the actual Gemini enrichment call ──────────────────
    img_tokens = total_images * IMAGE_TOKENS_EACH
    ctx_overhead = total_q * (PROMPT_SCAFFOLD_TOKENS + CONTEXT_CHUNKS * TOKENS_PER_CHUNK)
    proj_input = total_content + img_tokens + ctx_overhead
    proj_output = total_q * OUTPUT_TOKENS_PER_Q

    print("Projected Gemini job (one combined call per question)")
    print("-" * 82)
    print(f"  Raw question content tokens        : {fmt(total_content)}")
    print(f"  Image tokens ({total_images} imgs x {IMAGE_TOKENS_EACH})       : {fmt(img_tokens)}")
    print(f"  Prompt scaffold + {CONTEXT_CHUNKS} ctx chunks/Q     : {fmt(ctx_overhead)}")
    print(f"  => Projected INPUT tokens          : {fmt(proj_input)}")
    print(f"  => Projected OUTPUT tokens         : {fmt(proj_output)}")
    print(f"  => Projected TOTAL tokens          : {fmt(proj_input + proj_output)}\n")

    # ── Feasibility vs free tier (4 projects) ─────────────────────────────────
    rpd_ceiling = 4 * 1500
    days = (total_q + rpd_ceiling - 1) // rpd_ceiling
    print("Feasibility vs free tier (4 projects, ~1,500 RPD each)")
    print("-" * 82)
    print(f"  Calls needed (1/question)          : {fmt(total_q)}")
    print(f"  Daily ceiling (4 x 1,500)          : {fmt(rpd_ceiling)}")
    print(f"  Minimum days to finish             : {days}")
    print(f"  Avg input tokens per call          : {proj_input // total_q if total_q else 0}")
    print(f"  (TPM limit 250k @ ~10 RPM => ~25k tokens/call headroom; well within.)")


if __name__ == "__main__":
    main()
