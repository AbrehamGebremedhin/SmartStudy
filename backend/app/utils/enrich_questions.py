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
from sqlalchemy import delete, select, update
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


# Depth gate: the shallow-explanation defect this rebuild targets. A row passes only
# with a real step-by-step argument AND a reason for every wrong option.
MIN_EXPL_STEPS = 3
MIN_EXPL_CHARS = 220


def is_deep_enough(correct_answer, options, correct_expl, incorrect_expl) -> bool:
    if not is_structurally_valid(correct_answer, options, correct_expl, incorrect_expl):
        return False
    steps = [s for s in correct_expl if str(s).strip()]
    if len(steps) < MIN_EXPL_STEPS or sum(len(str(s)) for s in steps) < MIN_EXPL_CHARS:
        return False
    wrong = set(option_letters(options)) - {correct_answer}
    return set(incorrect_expl) == wrong and all(str(v).strip() for v in incorrect_expl.values())


# ── Gemini enrichment ─────────────────────────────────────────────────────────

# DeepSeek-tuned (positive framing, CO-STAR shape): DeepSeek largely ignores "never"
# constraints, so every rule states the desired behaviour with a concrete example.
SYSTEM_INSTRUCTION = (
    "# Role\n"
    "You are an expert Ethiopian EUEE exam tutor who writes deep, accurate answer explanations.\n"
    "# Task\n"
    "For the multiple-choice question given, identify the correct option and explain it thoroughly. "
    "Respond with a single strict JSON object and nothing else.\n"
    "# Explanation depth (the priority)\n"
    "- correct_explanations: an array of 3-5 full sentences forming a step-by-step argument — begin "
    "from the governing concept or principle, reason through to why the correct option follows, and "
    "end with the conclusion. The steps should teach, not merely assert.\n"
    "- incorrect_explanations: one entry per wrong option, each naming the specific misconception or "
    "error that makes that option wrong.\n"
    "- workout_steps: for quantitative questions, give the full numbered calculation with units; use "
    "null otherwise.\n"
    "- Identify each option by its content or meaning so every explanation is self-contained and "
    "stays correct regardless of option order.\n"
    "# Formatting\n"
    "- Write all mathematics in plain ASCII text, e.g. theta, sin, sqrt, 'F = B*I*l*sin(theta)', "
    "'B = mu_0*I/(2*pi*r)'. Use Greek letters as words (theta, mu) and ASCII operators.\n"
    "- correct_answer is the single letter (A, B, C, D, or E) of the correct option.\n"
    "# Curriculum context\n"
    "- Use the provided curriculum context only to choose an accurate topic label; base every "
    "explanation on general subject knowledge and the question itself.\n"
    "# Passage field\n"
    "- Provide passage text only when the question quotes a reading passage or sentence the student "
    "needs (mainly English/SAT reading and vocabulary); set passage to null for all other questions."
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


def _gen_schema_hint() -> str:
    return (
        '{"topic":"specific concept tested",'
        '"passage":"reading text the question needs, else null",'
        '"correct_answer":"SINGLE LETTER (A/B/C/D/E) — the option label, NOT its text",'
        '"answer_confidence":0.0-1.0,'
        '"correct_explanations":["step 1 (concept)","step 2 (reasoning)","step 3 (conclusion)"],'
        '"incorrect_explanations":{"<each wrong letter>":"the specific misconception that makes it wrong"},'
        '"workout_steps":"numbered calculation with units if quantitative, else null"}'
    )


# Few-shot exemplar (Gemini cookbook: "prompts without few-shot examples are likely to be
# less effective"). Sets the depth bar — concept→reasoning→conclusion + per-option misconceptions.
_FEWSHOT = """<example>
<question>A 2 kg object accelerates from rest to 6 m/s in 3 s. What is the net force on it?</question>
<options>
  A) 2 N
  B) 4 N
  C) 12 N
  D) 18 N
</options>
<output>
{"topic":"Newton's second law (F = ma)","passage":null,"correct_answer":"B","answer_confidence":1.0,
"correct_explanations":[
  "Newton's second law states the net force equals mass times acceleration, F = m*a, so the acceleration must be found first.",
  "Acceleration is the change in velocity over time: a = (6 m/s - 0) / 3 s = 2 m/s^2.",
  "Multiplying mass by acceleration gives F = 2 kg * 2 m/s^2 = 4 N, which matches the second option."],
"incorrect_explanations":{
  "A":"This uses the mass alone as if force equalled mass, ignoring acceleration entirely.",
  "C":"This multiplies mass by the final velocity (2*6) instead of by acceleration — a confusion of velocity with acceleration.",
  "D":"This multiplies mass by velocity and then by something else; it has no basis in F = m*a."},
"workout_steps":"1) a = dv/dt = 6/3 = 2 m/s^2.  2) F = m*a = 2*2 = 4 N."}
</output>
</example>"""


def build_gen_prompt(rec: dict, ctx: str) -> str:
    """One question per call — deep enrichment (the generation stage).

    Cookbook-aligned: role/format/rules live in SYSTEM_INSTRUCTION; here we give a
    worked example, then context, then the question last with a bridging instruction.
    """
    parts = [_FEWSHOT, "", "Now enrich the question below to the SAME depth and JSON shape."]
    if rec["has_image"]:
        parts.append("Diagrams are attached as images — read them carefully.")
    parts.append(f"\n## Subject\n{rec['subject']}")
    if ctx:
        parts.append(f"\n## Curriculum context (for grounding the topic ONLY — do not quote)\n{ctx}")
    if rec.get("official_answer"):
        parts.append(f"\n## Official correct answer (keep this; explain why it is right)\n{rec['official_answer']}")
    parts.append(f"\n## Question\n{rec['question']}")
    parts.append("\n## Options\n" + _options_block(rec["options"]))
    parts.append("\nBased on the above, return ONLY this JSON object:\n" + _gen_schema_hint())
    return "\n".join(parts)


def build_judge_prompt(batch: list[dict]) -> str:
    """Many questions per call — short verdicts (the validation stage)."""
    parts = [
        "You are validating already-written answer explanations for EUEE multiple-choice "
        "questions. For EACH item, independently decide the correct option, then judge the "
        "given answer and explanations. Return JSON: "
        '{"results":[{"index":<int>,"your_answer":"<letter>",'
        '"answer_agrees":<true if your_answer equals the given answer>,'
        '"depth_score":<1-5: how thorough/correct the explanations are>}]}\n',
    ]
    for item in batch:
        parts.append(f"### index {item['index']}")
        parts.append(f"Question: {item['question']}")
        parts.append("Options:\n" + _options_block(item["options"]))
        parts.append(f"Given answer: {item['correct_answer']}")
        parts.append("Given correct_explanations: " + " | ".join(item["correct_explanations"] or []))
        parts.append("")
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
    # `{"results": null}` -> .get returns None, not the default; coerce to [].
    return (data.get("results") or []) if isinstance(data, dict) else []


def _rec_image_fs(rec: dict) -> list[str]:
    return [fs for fs in ([rec.get("_question_image_fs")] + [o.get("_image_fs") for o in rec["options"]])
            if fs and os.path.exists(fs)]


# ── Ollama backend (local gemma4) ─────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434/api/chat"


def _png_b64(fs: str) -> str:
    """Ollama can't read .webp — transcode to PNG in memory."""
    import base64
    import io

    from PIL import Image
    im = Image.open(fs).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


async def ollama_generate(prompt: str, image_fs: list[str] | None, model: str,
                          think: bool = True) -> str:
    import requests
    msg = {"role": "user", "content": prompt}
    if image_fs:
        msg["images"] = [_png_b64(f) for f in image_fs]
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_INSTRUCTION}, msg],
        "stream": False, "format": "json", "think": think,
        "options": {"temperature": 0.2},
    }

    def _post() -> str:
        r = requests.post(OLLAMA_URL, json=body, timeout=900)
        r.raise_for_status()
        return r.json()["message"]["content"]
    return await asyncio.to_thread(_post)


# ── DeepSeek backend (cloud, text-only, parallel) ──────────────────────────────

def make_deepseek_llm():
    from langchain_deepseek import ChatDeepSeek
    # temperature 0: DeepSeek's own guidance for factual/maths work — maximizes accuracy.
    llm = ChatDeepSeek(model="deepseek-v4-flash", api_key=settings.deepseek_api_key,
                       temperature=0, max_retries=3)
    return llm.bind(response_format={"type": "json_object"})


async def deepseek_generate(llm, prompt: str) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage
    resp = await llm.ainvoke([SystemMessage(content=SYSTEM_INSTRUCTION), HumanMessage(content=prompt)])
    return resp.content if isinstance(resp.content, str) else str(resp.content)


def _parse_one(text: str) -> dict:
    """Parse a single enrichment object (gemma may wrap it as {'results':[obj]})."""
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            return {}
        try:
            data = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return {}
    if isinstance(data, dict) and isinstance(data.get("results"), list) and data["results"]:
        first = data["results"][0]
        return first if isinstance(first, dict) else {}
    return data if isinstance(data, dict) else {}


# ── Row building + upsert ─────────────────────────────────────────────────────

def to_letter(ans, options: list[dict]) -> str | None:
    """Normalize a model's answer to an option letter.

    Gemini returns the letter directly; gemma4 often returns the option *text*.
    Match a single valid letter first, else map the text back to its option.
    """
    letters = option_letters(options)
    a = (ans or "").strip()
    if len(a) <= 2 and a[:1].upper() in letters:
        return a[:1].upper()
    na = _norm(a)
    if na:
        for o in options:
            ot = _norm(o.get("text") or "")
            if ot and (ot == na or na in ot or ot in na):
                return o["letter"]
    if a[:1].upper() in letters:
        return a[:1].upper()
    # Last resort: best option by word overlap (handles paraphrased answers).
    atoks = set(na.split())
    if atoks:
        best, score = None, 0.0
        for o in options:
            otoks = set(_norm(o.get("text") or "").split())
            if otoks:
                jac = len(atoks & otoks) / len(atoks | otoks)
                if jac > score:
                    best, score = o["letter"], jac
        if score >= 0.5:
            return best
    return None


def build_row(rec: dict, enr: dict) -> dict:
    options = [{"letter": o["letter"], "text": o.get("text"), "image_url": o.get("image_url")}
               for o in rec["options"]]
    letters = option_letters(rec["options"])

    official = rec.get("official_answer")
    answer = to_letter(official or enr.get("correct_answer"), rec["options"]) or ""
    source = AnswerSource.official.value if official else AnswerSource.inferred.value
    confidence = None if official else enr.get("answer_confidence")

    # Passages only make sense for reading/vocab subjects. For STEM the model
    # sometimes dumps explanation text into `passage`; drop it deterministically.
    passage = enr.get("passage") if rec["subject"] in {"english", "sat"} else None

    # gemma4 sometimes misspells keys (e.g. "correct_explanasions"); match by prefix.
    def _pick(*prefixes):
        for k, v in enr.items():
            kn = k.replace("_", "").lower()
            if any(kn.startswith(p) for p in prefixes):
                return v
        return None

    correct_expl = _pick("correctexplan") or []
    # Keys may be letters (Gemini) or option text (gemma4) — normalize both to letters.
    incorrect_expl = {}
    for k, v in (_pick("incorrectexplan") or {}).items():
        letter = to_letter(k, rec["options"])
        if letter in letters and letter != answer:
            incorrect_expl[letter] = v

    # gemma4 sometimes returns text fields as lists — coerce to str for VARCHAR/Text cols.
    def _text(v):
        if v is None or isinstance(v, str):
            return v
        if isinstance(v, list):
            return "\n".join(str(x) for x in v)
        return str(v)

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
            "topic": _text(enr.get("topic")),
            "question": rec["question"],
            "passage": _text(passage),
            "question_image_url": rec["question_image_url"],
            "options": options,
            "correct_answer": answer or None,
            "answer_source": source,
            "answer_confidence": confidence,
            "correct_explanations": correct_expl,
            "incorrect_explanations": incorrect_expl,
            "workout_steps": _text(enr.get("workout_steps")),
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


# ── Progress helper ───────────────────────────────────────────────────────────

def _progress() -> Progress:
    return Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), MofNCompleteColumn(), TextColumn("·"),
        TimeElapsedColumn(), TextColumn("eta"), TimeRemainingColumn(),
        console=console,
    )


# ── Stage 1: gemma generation (local, 1 question/call, thinking on, depth-gated) ──

async def generate_stage(subject_filter: str | None, limit: int | None,
                         image_model: str, concurrency: int) -> None:
    records = load_unique_questions(subject_filter)
    done = await heal_and_get_done({r["content_hash"] for r in records})
    todo = [r for r in records if r["content_hash"] not in done]
    if limit:
        todo = todo[:limit]
    text_todo = [r for r in todo if not r["has_image"]]
    image_todo = [r for r in todo if r["has_image"]]
    console.print(f"[bold]Generate: {len(done)} done · {len(text_todo)} text (DeepSeek) "
                  f"+ {len(image_todo)} image (gemma)[/bold]")
    if not todo:
        return

    # Preflight: DeepSeek key for text, Ollama vision model for images.
    if text_todo and not settings.deepseek_api_key:
        sys.exit("DEEPSEEK_API_KEY not set in .env.")
    if image_todo:
        import requests
        try:
            names = {m["name"] for m in requests.get(
                "http://localhost:11434/api/tags", timeout=10).json().get("models", [])}
        except Exception as e:  # noqa: BLE001
            sys.exit(f"Cannot reach Ollama at localhost:11434: {e}")
        if image_model not in names:
            sys.exit(f"Ollama model {image_model!r} not found. Available: {sorted(names)}")

    retriever = RetrievalAgent()
    deepseek = make_deepseek_llm() if text_todo else None
    stats = {"ok": 0, "needs_review": 0, "retried": 0, "failed": 0}

    async def enrich(rec: dict, gen_fn):
        ctx = await resolve_grade_unit_context(retriever, rec)
        for attempt in (1, 2):
            try:
                text = await gen_fn(rec, ctx)
            except Exception as e:  # noqa: BLE001
                logger.error("gen failed %s (attempt %d): %s", rec["content_hash"][:8], attempt, e)
                continue
            row = build_row(rec, _parse_one(text))["row"]
            deep = is_deep_enough(row["correct_answer"], rec["options"],
                                  row["correct_explanations"], row["incorrect_explanations"])
            if deep:
                return row, attempt
            if attempt == 2 and row["correct_answer"]:   # usable but shallow → keep, flag
                row["needs_review"] = True
                logger.warning("shallow after retry %s", rec["content_hash"][:8])
                return row, attempt
        return None, 2

    async def ds_gen(rec, ctx):
        return await deepseek_generate(deepseek, build_gen_prompt(rec, ctx))

    async def gm_gen(rec, ctx):
        return await ollama_generate(build_gen_prompt(rec, ctx), _rec_image_fs(rec),
                                     model=image_model, think=True)

    n = {"done": 0}

    async def handle(rec, gen_fn, progress, task):
        row, attempt = await enrich(rec, gen_fn)
        if row is None:
            stats["failed"] += 1
        else:
            if attempt == 2:
                stats["retried"] += 1
            stats["needs_review" if row["needs_review"] else "ok"] += 1
            try:
                await upsert_rows([row])
            except Exception as e:  # noqa: BLE001
                logger.error("upsert failed %s: %s", rec["content_hash"][:8], e)
                stats["failed"] += 1
        n["done"] += 1
        progress.update(task, advance=1, description=f"gen · {stats}")
        if n["done"] % 25 == 0:
            write_checkpoint({"stage": "generate", "total": len(todo), "done_now": n["done"],
                              "already_done": len(done), "remaining": len(todo) - n["done"], "stats": stats})

    with _progress() as progress:
        task = progress.add_task("Generating", total=len(todo))
        # Text: parallel DeepSeek (cloud, no GPU limit).
        sem = asyncio.Semaphore(concurrency)

        async def bounded(rec):
            async with sem:
                await handle(rec, ds_gen, progress, task)
        if text_todo:
            await asyncio.gather(*(bounded(r) for r in text_todo))
        # Images: serial gemma (single GPU).
        for rec in image_todo:
            await handle(rec, gm_gen, progress, task)

    write_checkpoint({"stage": "generate", "total": len(todo), "done_now": n["done"],
                      "already_done": len(done), "remaining": len(todo) - n["done"], "stats": stats})
    console.print(f"[green bold]Generate done.[/green bold] {stats}")


# ── Stage 2: gemini validation (cloud, batched judge, short verdicts) ────────────

JUDGE_SYSTEM = ("You are a meticulous EUEE exam answer-key validator. For each question, work out "
                "the correct option yourself, then judge the supplied answer and explanations. "
                "Output strict JSON only.")
JUDGE_BATCH = 15


async def validate_stage(judge_model: str, limit: int | None) -> None:
    keys = settings.gemini_api_keys
    if not keys:
        sys.exit("No Gemini keys configured (set GEMINI_API_KEY_1..4 in .env).")
    pool = GeminiKeyPool(keys, model=judge_model)

    async with AsyncSessionLocal() as db:
        q = select(ExamQuestion).where(ExamQuestion.validation_score.is_(None))
        if limit:
            q = q.limit(limit)
        rows = (await db.execute(q)).scalars().all()
        items = [{"id": r.id, "question": r.question, "options": r.options,
                  "correct_answer": r.correct_answer, "correct_explanations": r.correct_explanations,
                  "needs_review": r.needs_review} for r in rows]
    console.print(f"[bold]Validate: {len(items)} rows to judge[/bold]")
    if not items:
        return

    stats = {"agree": 0, "disagree": 0, "low_depth": 0}
    batches = [items[i:i + JUDGE_BATCH] for i in range(0, len(items), JUDGE_BATCH)]
    # One in-flight batch per key — the pool rotates keys, so each key sees ~1 call
    # at a time (well under its RPM); no manual pacing needed.
    concurrency = max(2, len(settings.gemini_api_keys))
    sem = asyncio.Semaphore(concurrency)
    n = {"done": 0}

    async def judge(batch, progress, task):
        jbatch = [{"index": j, **b} for j, b in enumerate(batch)]
        async with sem:
            try:
                text = await pool.generate(build_judge_prompt(jbatch), system_instruction=JUDGE_SYSTEM)
                verdicts = {int(v["index"]): v for v in _parse_results(text)
                            if isinstance(v, dict) and "index" in v}
            except Exception as e:  # noqa: BLE001 — failed batch leaves rows unvalidated; rerun picks them up
                logger.error("judge batch failed: %s", e)
                verdicts = {}

        updates = []
        for j, b in enumerate(batch):
            v = verdicts.get(j)
            if not v:
                continue
            judged = to_letter(v.get("your_answer"), b["options"])
            agrees = (judged == b["correct_answer"]) if judged else bool(v.get("answer_agrees"))
            try:
                depth = int(v.get("depth_score") or 0)
            except (ValueError, TypeError):
                depth = 0
            needs_review = b["needs_review"] or (not agrees) or depth < 3
            updates.append((b["id"], depth, agrees, needs_review))
            stats["agree" if agrees else "disagree"] += 1
            if depth < 3:
                stats["low_depth"] += 1

        if updates:
            async with AsyncSessionLocal() as db:
                for rid, depth, agrees, nr in updates:
                    await db.execute(update(ExamQuestion).where(ExamQuestion.id == rid)
                                     .values(validation_score=depth, answer_agreed=agrees, needs_review=nr))
                await db.commit()
        n["done"] += len(batch)
        progress.update(task, advance=len(batch), description=f"judge · {pool.status_line()}")
        if n["done"] % (JUDGE_BATCH * concurrency) < JUDGE_BATCH:
            write_checkpoint({"stage": "validate", "total": len(items), "done_now": n["done"],
                              "stats": stats, "keys": pool.status_line()})

    with _progress() as progress:
        task = progress.add_task("Validating (gemini)", total=len(items))
        await asyncio.gather(*(judge(b, progress, task) for b in batches))

    write_checkpoint({"stage": "validate", "total": len(items), "done_now": n["done"],
                      "stats": stats, "keys": pool.status_line()})
    console.print(f"[green bold]Validate done.[/green bold] {stats} · Gemini calls={pool.total_calls()}")


# ── Dispatcher ──────────────────────────────────────────────────────────────────

async def run(stage: str, subject_filter: str | None, limit: int | None,
              image_model: str, judge_model: str, concurrency: int, reset: bool) -> None:
    if reset:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(ExamQuestion))
            await db.commit()
        console.print("[yellow]--reset: cleared exam_questions.[/yellow]")
    if stage in ("generate", "all"):
        await generate_stage(subject_filter, limit, image_model, concurrency)
    if stage in ("validate", "all"):
        await validate_stage(judge_model, limit)


def main() -> None:
    ap = argparse.ArgumentParser(description="Enrich scraped exam questions into exam_questions.")
    ap.add_argument("--stage", choices=["generate", "validate", "all"], default="all",
                    help="generate (DeepSeek text + gemma image), validate (gemini judge), or all")
    ap.add_argument("--subject", help="Canonical subject filter, e.g. biology, maths, sat")
    ap.add_argument("--limit", type=int, help="Cap number of questions (dry-run)")
    ap.add_argument("--image-model", default="gemma4:latest", help="Ollama vision model for image questions")
    ap.add_argument("--judge-model", default="gemini-2.5-flash", help="Gemini validation model")
    ap.add_argument("--concurrency", type=int, default=20, help="Parallel DeepSeek text calls")
    ap.add_argument("--reset", action="store_true", help="Wipe exam_questions before running")
    args = ap.parse_args()
    asyncio.run(run(args.stage, args.subject, args.limit, args.image_model,
                    args.judge_model, args.concurrency, args.reset))


if __name__ == "__main__":
    main()
