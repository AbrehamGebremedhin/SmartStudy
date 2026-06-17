#!/usr/bin/env python3
"""
Exam-question enrichment pipeline.

Turns the scraped EUEE/model/Tigray questions into MCQ-compatible `exam_questions`
rows: resolves grade/unit/topic locally via Milvus (zero Gemini quota) and uses a
rotating pool of Gemini keys to solve answers + write explanations.

Design highlights
-----------------
* Idempotent + crash-safe: every source question has a stable `content_hash`
  (unique column). The DB is the source of truth. On startup the script DELETES
  any structurally-malformed rows (so they get redone) and processes only the
  questions that don't yet have a valid row — i.e. it resumes from the last fully
  finished question and rewrites anything malformed after it.
* Per-batch atomic commits: a crash mid-batch rolls back, leaving no half rows.
* Local resolution: grade/unit from Milvus metadata vote; topic from Gemini using
  a short retrieved-context snippet.
* Batched text questions (cheap), individual multimodal calls for the ~233 image
  questions.
* Live progress via rich, mirrored to euee_output/enrich_checkpoint.json.

Usage
-----
    python -m app.utils.enrich_questions --subject biology --limit 50   # dry run
    python -m app.utils.enrich_questions                                # full run
    python -m app.utils.enrich_questions --reset                        # wipe + restart
"""

import argparse
import asyncio
import glob
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import orjson
from rich.console import Console
from rich.progress import (BarColumn, MofNCompleteColumn, Progress, SpinnerColumn,
                           TextColumn, TimeElapsedColumn, TimeRemainingColumn)
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

# Agents use bare imports; put the agents dir on the path (mirrors services/generation.py).
_AGENTS = str(Path(__file__).resolve().parents[1] / "agents")
if _AGENTS not in sys.path:
    sys.path.insert(0, _AGENTS)

from app.config import settings                       # noqa: E402
from app.db.database import AsyncSessionLocal         # noqa: E402
from app.db.models import AnswerSource, ExamQuestion  # noqa: E402
from gemini_pool import GeminiKeyPool                 # noqa: E402
from RetrievalAgent import RetrievalAgent             # noqa: E402

console = Console()
REPO_ROOT = Path(__file__).resolve().parents[3]
EUEE_DIR = REPO_ROOT / "euee_output"
CHECKPOINT = EUEE_DIR / "enrich_checkpoint.json"

# force=True: RetrievalAgent calls logging.basicConfig() at import (a StreamHandler),
# which would otherwise make this a no-op and send all logs to stderr instead of the file.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(EUEE_DIR / "enrich.log", encoding="utf-8")],
    force=True,
)
logger = logging.getLogger("enrich")

CHOICE_LETTERS = ["A", "B", "C", "D", "E"]
CONF_REVIEW_THRESHOLD = 0.6
NO_GRADE_UNIT = {"sat", "english"}  # cross-grade supplements with no grade/unit metadata

# ── Subject normalization ─────────────────────────────────────────────────────

_SUBJECT_PATTERNS = [
    ("maths", ("math",)),
    ("sat", ("scholastic", "aptitude", "sat")),
    ("biology", ("biolog",)),
    ("chemistry", ("chemist",)),
    ("physics", ("physic",)),
    ("english", ("english",)),
    ("civics", ("civic",)),
    ("economics", ("econom",)),
    ("geography", ("geograph",)),
    ("history", ("histor",)),
]


def canonical_subject(raw: str) -> str | None:
    s = (raw or "").lower()
    for canonical, needles in _SUBJECT_PATTERNS:
        if any(n in s for n in needles):
            return canonical
    return None


# ── Source loading + dedup ────────────────────────────────────────────────────

def find_latest_json() -> Path:
    files = glob.glob(str(EUEE_DIR / "euee_*.json"))
    if not files:
        sys.exit("No euee_*.json found in euee_output/")
    return Path(max(files, key=os.path.getmtime))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _img_local_path(image_obj: dict | None) -> str | None:
    if image_obj and image_obj.get("local_path"):
        return image_obj["local_path"]
    return None


def _image_url(local_path: str | None) -> str | None:
    """Map a scraped local_path ('images/<dir>/<f>') to the served static URL."""
    if not local_path:
        return None
    rel = local_path[len("images/"):] if local_path.startswith("images/") else local_path
    return f"/static/exam-images/{rel}"


def _image_fs_path(local_path: str | None) -> Path | None:
    if not local_path:
        return None
    return EUEE_DIR / local_path


def content_hash(subject: str, question: str, choices: list[dict]) -> str:
    sig = [_norm(subject), _norm(question)]
    for c in choices:
        token = c.get("text") or _img_local_path(c.get("image")) or ""
        sig.append(f"{c.get('letter', '')}:{_norm(token)}")
    return hashlib.sha256("".join(sig).encode("utf-8")).hexdigest()


def load_unique_questions(subject_filter: str | None) -> list[dict]:
    """Parse the scrape, normalize subjects, dedup by content_hash, return records."""
    path = find_latest_json()
    with open(path, "rb") as f:
        exams = orjson.loads(f.read())

    seen: set[str] = set()
    records: list[dict] = []
    skipped_subject = 0

    for exam in exams:
        subj = canonical_subject(exam.get("Subject", ""))
        if subj is None:
            skipped_subject += 1
            continue
        if subject_filter and subj != subject_filter:
            continue
        for q in exam.get("Questions", []):
            choices = q.get("Choices", [])
            if not q.get("Question") or len(choices) < 2:
                continue
            ch = content_hash(subj, q["Question"], choices)
            if ch in seen:
                continue
            seen.add(ch)
            options = [
                {
                    "letter": c.get("letter"),
                    "text": c.get("text"),
                    "image_url": _image_url(_img_local_path(c.get("image"))),
                    "_image_fs": str(p) if (p := _image_fs_path(_img_local_path(c.get("image")))) else None,
                }
                for c in choices if c.get("letter") in CHOICE_LETTERS
            ]
            q_img_lp = _img_local_path(q.get("Question_image"))
            records.append({
                "content_hash": ch,
                "subject": subj,
                "original_subject": exam.get("Subject", ""),
                "stream": exam.get("Stream"),
                "year": exam.get("Year"),
                "exam_name": exam.get("ExamName"),
                "number": q.get("Number"),
                "question": q["Question"],
                "question_image_url": _image_url(q_img_lp),
                "_question_image_fs": str(p) if (p := _image_fs_path(q_img_lp)) else None,
                "options": options,
                "official_answer": q.get("Correct_choice"),
                "has_image": bool(q_img_lp) or any(o["image_url"] for o in options),
            })

    console.print(f"[dim]Loaded {len(records)} unique questions "
                  f"(deduped; {skipped_subject} exams with unknown subject skipped) from {path.name}[/dim]")
    return records


# ── Validation ────────────────────────────────────────────────────────────────

def option_letters(options: list[dict]) -> list[str]:
    return [o["letter"] for o in options if o.get("letter")]


def is_structurally_valid(correct_answer, options, correct_expl, incorrect_expl) -> bool:
    letters = option_letters(options)
    return (
        correct_answer in letters
        and isinstance(correct_expl, list) and len(correct_expl) > 0
        and isinstance(incorrect_expl, dict)
    )


# ── Gemini enrichment ─────────────────────────────────────────────────────────

SYSTEM_INSTRUCTION = (
    "You are an expert Ethiopian EUEE exam tutor. For each multiple-choice question you "
    "receive, determine the correct option, and write clear, factually accurate explanations. "
    "Refer to options by their content, never by letter, inside explanations. Output strict JSON only.\n"
    "PASSAGE RULE (critical): set \"passage\" to null UNLESS the question literally cannot be "
    "answered without an accompanying reading passage, quoted sentence, or fill-in-the-blank "
    "sentence that belongs to the question itself (mainly English/SAT reading & vocabulary). "
    "For virtually all physics, chemistry, biology, maths, and standalone questions, passage MUST "
    "be null. NEVER put curriculum context, source text, or your own explanation in passage.\n"
    "CONTEXT RULE: the 'Curriculum context' provided is ONLY to help you label the topic. Never "
    "copy it into any field and never reference it in explanations (no 'the context says', 'the "
    "source states', 'Exercise 4.1', etc.). Explanations must stand on general subject knowledge."
)


def _options_block(options: list[dict]) -> str:
    lines = []
    for o in options:
        if o.get("text"):
            lines.append(f'  {o["letter"]}) {o["text"]}')
        elif o.get("image_url"):
            lines.append(f'  {o["letter"]}) [IMAGE OPTION]')
        else:
            lines.append(f'  {o["letter"]}) [blank]')
    return "\n".join(lines)


def _output_schema_hint(letters: list[str]) -> str:
    return (
        '{"results":[{"index":<int>,"topic":"specific concept tested",'
        '"passage":"reading passage/quoted text the question needs, else null",'
        '"correct_answer":"one of ' + "".join(letters) + '",'
        '"answer_confidence":0.0-1.0,'
        '"correct_explanations":["step 1","step 2"],'
        '"incorrect_explanations":{"<wrong letter>":"why it is wrong"},'
        '"workout_steps":"calculation steps if any, else null"}]}'
    )


def build_text_batch_prompt(batch: list[dict]) -> str:
    parts = [
        "Enrich each question below. Return JSON exactly as specified — one result per "
        "question, matched by index. incorrect_explanations must contain an entry for every "
        "option letter EXCEPT the correct one. If an official answer is given, explain that "
        "answer (do not change it); otherwise determine the answer yourself.\n",
    ]
    for item in batch:
        rec = item["rec"]
        ctx = item["context"]
        parts.append(f"### index {item['index']}")
        parts.append(f"Subject: {rec['subject']}")
        if ctx:
            parts.append(f"Curriculum context (for grounding the topic): {ctx}")
        if rec.get("official_answer"):
            parts.append(f"Official correct answer (keep this): {rec['official_answer']}")
        parts.append(f"Question: {rec['question']}")
        parts.append("Options:\n" + _options_block(rec["options"]))
        parts.append("")
    letters = CHOICE_LETTERS
    parts.append("Return ONLY this JSON shape:\n" + _output_schema_hint(letters))
    return "\n".join(parts)


def build_single_prompt(rec: dict, ctx: str) -> str:
    parts = ["Enrich this exam question. Some content is shown as images below."]
    parts.append(f"Subject: {rec['subject']}")
    if ctx:
        parts.append(f"Curriculum context (for grounding the topic): {ctx}")
    if rec.get("official_answer"):
        parts.append(f"Official correct answer (keep this): {rec['official_answer']}")
    parts.append(f"Question: {rec['question']}")
    parts.append("Options:\n" + _options_block(rec["options"]))
    parts.append("Return ONLY this JSON shape (single-element results array):\n"
                 + _output_schema_hint(CHOICE_LETTERS))
    return "\n".join(parts)


def _parse_results(text: str) -> list[dict]:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            return []
        try:
            data = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return []
    if isinstance(data, list):
        return data
    return data.get("results", []) if isinstance(data, dict) else []


def _image_parts(rec: dict):
    from google.genai import types
    parts = []
    for fs in [rec.get("_question_image_fs")] + [o.get("_image_fs") for o in rec["options"]]:
        if fs and os.path.exists(fs):
            with open(fs, "rb") as fh:
                parts.append(types.Part.from_bytes(data=fh.read(), mime_type="image/webp"))
    return parts


# ── Row building + upsert ─────────────────────────────────────────────────────

def build_row(rec: dict, enr: dict) -> dict:
    options = [{"letter": o["letter"], "text": o.get("text"), "image_url": o.get("image_url")}
               for o in rec["options"]]
    letters = option_letters(rec["options"])

    official = rec.get("official_answer")
    answer = (official or enr.get("correct_answer") or "").strip().upper()[:1]
    source = AnswerSource.official.value if official else AnswerSource.inferred.value
    confidence = None if official else enr.get("answer_confidence")

    # Passages only make sense for reading/vocab subjects. For STEM the model
    # sometimes dumps explanation text into `passage`; drop it deterministically.
    passage = enr.get("passage") if rec["subject"] in {"english", "sat"} else None

    correct_expl = enr.get("correct_explanations") or []
    incorrect_expl = {k.upper(): v for k, v in (enr.get("incorrect_explanations") or {}).items()
                      if k.upper() in letters and k.upper() != answer}

    structurally_ok = is_structurally_valid(answer, rec["options"], correct_expl, incorrect_expl)
    complete = structurally_ok and set(incorrect_expl) == set(letters) - {answer}
    needs_review = (not complete) or (confidence is not None and float(confidence) < CONF_REVIEW_THRESHOLD)

    return {
        "_structurally_ok": structurally_ok,
        "row": {
            "content_hash": rec["content_hash"],
            "subject": rec["subject"],
            "original_subject": rec["original_subject"],
            "stream": rec["stream"],
            "year": rec["year"],
            "exam_name": rec["exam_name"],
            "number": rec["number"],
            "grade": rec.get("grade"),
            "unit": rec.get("unit"),
            "topic": enr.get("topic"),
            "question": rec["question"],
            "passage": passage,
            "question_image_url": rec["question_image_url"],
            "options": options,
            "correct_answer": answer or None,
            "answer_source": source,
            "answer_confidence": confidence,
            "correct_explanations": correct_expl,
            "incorrect_explanations": incorrect_expl,
            "workout_steps": enr.get("workout_steps"),
            "difficulty": "hard",
            "needs_review": needs_review,
        },
    }


async def upsert_rows(rows: list[dict]) -> None:
    if not rows:
        return
    async with AsyncSessionLocal() as db:
        stmt = pg_insert(ExamQuestion).values(rows)
        update_cols = {c: stmt.excluded[c] for c in rows[0] if c != "content_hash"}
        stmt = stmt.on_conflict_do_update(index_elements=["content_hash"], set_=update_cols)
        await db.execute(stmt)
        await db.commit()


# ── Resume / self-heal ────────────────────────────────────────────────────────

async def heal_and_get_done(content_hashes: set[str]) -> set[str]:
    """Delete malformed rows; return the set of content_hashes already valid in the DB."""
    deleted = 0
    done: set[str] = set()
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(
                ExamQuestion.content_hash, ExamQuestion.correct_answer,
                ExamQuestion.options, ExamQuestion.correct_explanations,
                ExamQuestion.incorrect_explanations,
            )
        )).all()
        bad: list[str] = []
        for ch, ans, opts, cexp, iexp in rows:
            if ch not in content_hashes:
                continue  # row from a different run/subject — leave it
            if is_structurally_valid(ans, opts or [], cexp, iexp):
                done.add(ch)
            else:
                bad.append(ch)
        if bad:
            await db.execute(delete(ExamQuestion).where(ExamQuestion.content_hash.in_(bad)))
            await db.commit()
            deleted = len(bad)
    if deleted:
        console.print(f"[yellow]Self-heal: removed {deleted} malformed row(s) to be rewritten.[/yellow]")
    return done


def write_checkpoint(snapshot: dict) -> None:
    snapshot["updated_at"] = datetime.now(timezone.utc).isoformat()
    CHECKPOINT.write_bytes(orjson.dumps(snapshot, option=orjson.OPT_INDENT_2))


# ── Milvus resolution (local, free) ───────────────────────────────────────────

async def resolve_grade_unit_context(retriever: RetrievalAgent, rec: dict) -> str:
    """Vote grade/unit from Milvus metadata; return a short context snippet for the topic."""
    try:
        docs = await retriever.query_vector_store(
            subject=rec["subject"], question=rec["question"],
            grade=None, unit=None, type_req="quiz",
        )
    except Exception as e:  # noqa: BLE001 — never let one lookup kill the run
        logger.warning("Milvus lookup failed for %s: %s", rec["content_hash"][:8], e)
        return ""

    top = docs[:5]
    if rec["subject"] not in NO_GRADE_UNIT:
        from collections import Counter
        grades = [str(d.metadata.get("grade")) for d in top if d.metadata.get("grade")]
        units = [str(d.metadata.get("unit")) for d in top if d.metadata.get("unit")]
        if grades:
            try:
                rec["grade"] = int(Counter(grades).most_common(1)[0][0])
            except (ValueError, TypeError):
                pass
        if units:
            rec["unit"] = Counter(units).most_common(1)[0][0]
    return " ".join(d.page_content for d in docs[:3])[:1500]


# ── Main run ──────────────────────────────────────────────────────────────────

async def run(subject_filter: str | None, limit: int | None, batch_size: int,
              model: str, reset: bool) -> None:
    keys = settings.gemini_api_keys
    if not keys:
        sys.exit("No Gemini keys configured (set GEMINI_API_KEY_1..4 in .env).")
    if len(keys) < 4:
        console.print(f"[yellow]Warning: only {len(keys)} Gemini key(s) loaded; "
                      f"throughput/quota will be limited.[/yellow]")

    if reset:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(ExamQuestion))
            await db.commit()
        console.print("[yellow]--reset: cleared exam_questions.[/yellow]")

    records = load_unique_questions(subject_filter)
    all_hashes = {r["content_hash"] for r in records}
    done = await heal_and_get_done(all_hashes)
    todo = [r for r in records if r["content_hash"] not in done]
    if limit:
        todo = todo[:limit]

    console.print(f"[bold]{len(done)} already done · {len(todo)} to process"
                  f"{f' (capped at {limit})' if limit else ''}[/bold]")
    if not todo:
        console.print("[green]Nothing to do — all questions enriched.[/green]")
        return

    pool = GeminiKeyPool(keys, model=model)
    retriever = RetrievalAgent()
    text_todo = [r for r in todo if not r["has_image"]]
    image_todo = [r for r in todo if r["has_image"]]

    stats = {"official": 0, "inferred": 0, "needs_review": 0, "failed": 0}

    async def process_batch(batch_recs: list[dict], multimodal: bool) -> None:
        # Resolve grade/unit/context locally first (free).
        for rec in batch_recs:
            rec["_ctx"] = await resolve_grade_unit_context(retriever, rec)
        try:
            if multimodal:
                rec = batch_recs[0]
                contents = [build_single_prompt(rec, rec["_ctx"]), *_image_parts(rec)]
                text = await pool.generate(contents, system_instruction=SYSTEM_INSTRUCTION)
                results = _parse_results(text)
                if not results:
                    logger.warning("Empty multimodal parse for %s; raw=%r",
                                   rec["content_hash"][:8], (text or "")[:300])
                results = [{**(results[0] if results else {}), "index": 0}]
            else:
                items = [{"index": i, "rec": r, "context": r["_ctx"]} for i, r in enumerate(batch_recs)]
                prompt = build_text_batch_prompt(items)
                text = await pool.generate(prompt, system_instruction=SYSTEM_INSTRUCTION)
                results = _parse_results(text)
        except Exception as e:  # noqa: BLE001
            logger.error("Gemini batch failed (%d q): %s", len(batch_recs), e)
            stats["failed"] += len(batch_recs)
            return

        by_index = {int(r["index"]): r for r in results if "index" in r}
        rows = []
        for i, rec in enumerate(batch_recs):
            enr = by_index.get(i)
            if not enr:
                stats["failed"] += 1
                continue
            built = build_row(rec, enr)
            if not built["_structurally_ok"]:
                logger.warning("Structurally invalid for %s: ans=%r expl=%d enr_keys=%s",
                               rec["content_hash"][:8], built["row"]["correct_answer"],
                               len(built["row"]["correct_explanations"]), list(enr.keys()))
                stats["failed"] += 1
                continue
            row = built["row"]
            rows.append(row)
            stats["official" if row["answer_source"] == "official" else "inferred"] += 1
            if row["needs_review"]:
                stats["needs_review"] += 1
        await upsert_rows(rows)  # atomic per batch

    columns = [
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), MofNCompleteColumn(), TextColumn("·"),
        TimeElapsedColumn(), TextColumn("eta"), TimeRemainingColumn(),
    ]
    total = len(text_todo) + len(image_todo)
    processed = 0
    with Progress(*columns, console=console) as progress:
        task = progress.add_task("Enriching", total=total)

        # Text questions in batches.
        for i in range(0, len(text_todo), batch_size):
            batch = text_todo[i:i + batch_size]
            await process_batch(batch, multimodal=False)
            processed += len(batch)
            progress.update(task, advance=len(batch),
                            description=f"text · keys[{pool.status_line()}]")
            write_checkpoint({
                "total": total, "done_now": processed, "already_done": len(done),
                "remaining": total - processed, "last_content_hash": batch[-1]["content_hash"],
                "stats": stats, "keys": pool.status_line(),
            })

        # Image questions one at a time (multimodal).
        for rec in image_todo:
            await process_batch([rec], multimodal=True)
            processed += 1
            progress.update(task, advance=1, description=f"image · keys[{pool.status_line()}]")
            write_checkpoint({
                "total": total, "done_now": processed, "already_done": len(done),
                "remaining": total - processed, "last_content_hash": rec["content_hash"],
                "stats": stats, "keys": pool.status_line(),
            })

    console.print(f"\n[green bold]Done.[/green bold] official={stats['official']} "
                  f"inferred={stats['inferred']} needs_review={stats['needs_review']} "
                  f"failed={stats['failed']} · Gemini calls={pool.total_calls()}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Enrich scraped exam questions into exam_questions.")
    ap.add_argument("--subject", help="Canonical subject filter, e.g. biology, maths, sat")
    ap.add_argument("--limit", type=int, help="Cap number of questions (dry-run)")
    ap.add_argument("--batch-size", type=int, default=10, help="Text questions per Gemini call")
    ap.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    ap.add_argument("--reset", action="store_true", help="Wipe exam_questions before running")
    args = ap.parse_args()
    asyncio.run(run(args.subject, args.limit, args.batch_size, args.model, args.reset))


if __name__ == "__main__":
    main()
