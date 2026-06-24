import math
import random
import uuid

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import verify_app_token
from app.core.curriculum_validation import validate_curriculum_params
from app.core.exceptions import OutOfContextError
from app.db import crud
from app.db.database import get_db
from app.schemas.requests import FlashcardRequest, MCQRequest, NotesRequest
from app.services import jobs
from app.services.cache import POOL_FRESH_RATIO, _parse_token_usage, compute_request_hash

router = APIRouter(prefix="/ws", tags=["WebSocket"])


def _format_chat_context(messages) -> str:
    lines, concepts = [], []
    for m in messages:
        if m.role == "user":
            lines.append(f"Student: {m.content}")
        elif m.role == "assistant":
            lines.append(f"Teacher: {m.content}")
            for c in (m.key_concepts or []):
                if c not in concepts:
                    concepts.append(c)
    result = "\n".join(lines)
    if concepts:
        result += f"\n\nKey concepts covered: {', '.join(concepts)}"
    return result


def _prog(stage: str, idx: int, total: int, label: str) -> dict:
    return {"type": "progress", "stage": stage, "stage_index": idx, "total_stages": total, "label": label}


async def _auth_ws(websocket: WebSocket, token: str, db: AsyncSession):
    """Return the authenticated User or None (closes socket on failure)."""
    try:
        payload = await verify_app_token(token)
    except Exception:
        await websocket.close(code=4001, reason="Unauthorized")
        return None
    google_id = payload.get("sub")
    email = payload.get("email", "")
    if not google_id:
        await websocket.close(code=4001, reason="Unauthorized")
        return None
    user, _ = await crud.get_or_create_user(db, clerk_id=google_id, email=email)
    return user


@router.websocket("/generate/notes")
async def ws_generate_notes(
    websocket: WebSocket,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> None:
    await websocket.accept()
    user = await _auth_ws(websocket, token, db)
    if not user:
        return

    TOTAL = 5
    try:
        data = await websocket.receive_json()
        body = NotesRequest(**data)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"type": "error", "code": "invalid_input", "detail": str(exc)})
        await websocket.close()
        return

    try:
        await websocket.send_json(_prog("validating", 0, TOTAL, "Validating your request…"))
        validate_curriculum_params(body.subject, body.grade, body.unit)

        params = {
            "subject": body.subject,
            "topic": body.topic,
            "grade": body.grade,
            "unit": body.unit,
            "chat_session_id": str(body.chat_session_id) if body.chat_session_id else None,
            "version": body.version,
        }
        request_hash = compute_request_hash(params)

        await websocket.send_json(_prog("cache_check", 1, TOTAL, "Checking for cached content…"))
        cached = await crud.get_cached_generation(db, request_hash, "notes")
        if cached:
            await crud.link_user_generation(db, user.id, cached.id, was_cache_hit=True)
            await db.commit()
            await websocket.send_json({
                "type": "result",
                "data": {
                    "generation_id": str(cached.id),
                    "was_cache_hit": True,
                    "notes": cached.content["notes"],
                },
            })
            await websocket.close()
            return

        await websocket.send_json(_prog("loading_context", 2, TOTAL, "Searching curriculum documents…"))
        chat_context: str | None = None
        if body.chat_session_id:
            chat_session = await crud.get_chat_session_with_messages(db, body.chat_session_id, user.id)
            if not chat_session:
                await websocket.send_json({"type": "error", "code": "not_found", "detail": "Chat session not found."})
                return
            chat_context = _format_chat_context(chat_session.messages)

        await websocket.send_json(_prog("generating", 3, TOTAL, "Writing your study notes…"))
        result = await jobs.submit_and_wait("generate_notes", {
            "subject": body.subject,
            "topic": body.topic,
            "grade": body.grade,
            "unit": body.unit,
            "version": body.version,
            "chat_context": chat_context,
        })

        if result.get("error"):
            error_code = result["error"]
            await websocket.send_json({"type": "error", "code": error_code, "detail": result.get("message", str(error_code))})
            await websocket.close()
            return

        await websocket.send_json(_prog("saving", 4, TOTAL, "Saving to your library…"))
        input_tokens, output_tokens, cost_usd = _parse_token_usage(result.get("token_usage"))
        generation = await crud.save_generation(
            db,
            generation_type="notes",
            request_hash=request_hash,
            request_params=params,
            content={"notes": result["notes"]},
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )
        await crud.link_user_generation(db, user.id, generation.id, was_cache_hit=False)
        await db.commit()

        await websocket.send_json({
            "type": "result",
            "data": {
                "generation_id": str(generation.id),
                "was_cache_hit": False,
                "notes": result["notes"],
                "token_usage": result.get("token_usage"),
            },
        })
        await websocket.close()

    except WebSocketDisconnect:
        pass
    except OutOfContextError as exc:
        await websocket.send_json({"type": "error", "code": "out_of_context", "detail": exc.message})
        await websocket.close()
    except Exception:
        await websocket.send_json({"type": "error", "code": "server_error", "detail": "An unexpected error occurred."})
        await websocket.close()


@router.websocket("/generate/mcq")
async def ws_generate_mcq(
    websocket: WebSocket,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> None:
    await websocket.accept()
    user = await _auth_ws(websocket, token, db)
    if not user:
        return

    TOTAL = 5
    try:
        data = await websocket.receive_json()
        body = MCQRequest(**data)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"type": "error", "code": "invalid_input", "detail": str(exc)})
        await websocket.close()
        return

    try:
        await websocket.send_json(_prog("validating", 0, TOTAL, "Validating parameters…"))
        validate_curriculum_params(body.subject, body.grade, body.unit)

        # Contextual (note/chat grounded): exact-hash caching, items must not mix with pool
        if body.note_id or body.chat_session_id:
            params = {
                "subject": body.subject,
                "grade": body.grade,
                "unit": body.unit,
                "topic": body.topic,
                "note_id": str(body.note_id) if body.note_id else None,
                "chat_session_id": str(body.chat_session_id) if body.chat_session_id else None,
                "num_questions": body.num_questions,
                "difficulty": body.difficulty,
            }
            request_hash = compute_request_hash(params)

            await websocket.send_json(_prog("cache_check", 1, TOTAL, "Checking for cached questions…"))
            cached = await crud.get_cached_generation(db, request_hash, "mcq")
            if cached:
                await crud.link_user_generation(db, user.id, cached.id, was_cache_hit=True)
                await db.commit()
                await websocket.send_json({
                    "type": "result",
                    "data": {
                        "generation_id": str(cached.id),
                        "was_cache_hit": True,
                        "questions": cached.content["questions"],
                        "difficulty": cached.content.get("difficulty", body.difficulty),
                    },
                })
                await websocket.close()
                return

            await websocket.send_json(_prog("loading_context", 2, TOTAL, "Loading curriculum context…"))
            note_content: dict | None = None
            chat_context: str | None = None
            if body.note_id:
                note_gen = await crud.get_generation_for_user(db, user.id, body.note_id, "notes")
                if not note_gen:
                    await websocket.send_json({"type": "error", "code": "not_found", "detail": "Note not found."})
                    await websocket.close()
                    return
                note_content = note_gen.content.get("notes")
            if body.chat_session_id:
                chat_session = await crud.get_chat_session_with_messages(db, body.chat_session_id, user.id)
                if not chat_session:
                    await websocket.send_json({"type": "error", "code": "not_found", "detail": "Chat session not found."})
                    await websocket.close()
                    return
                chat_context = _format_chat_context(chat_session.messages)

            n = body.num_questions
            await websocket.send_json(_prog("generating", 3, TOTAL, f"Crafting {n} question{'s' if n != 1 else ''}…"))
            result = await jobs.submit_and_wait("generate_mcq", {
                "subject": body.subject, "grade": body.grade, "unit": body.unit, "topic": body.topic,
                "num_questions": body.num_questions, "difficulty": body.difficulty,
                "note_content": note_content, "chat_context": chat_context,
            })
            if result.get("error"):
                await websocket.send_json({"type": "error", "code": result["error"], "detail": str(result["error"])})
                await websocket.close()
                return

            await websocket.send_json(_prog("saving", 4, TOTAL, "Saving…"))
            input_tokens, output_tokens, cost_usd = _parse_token_usage(result.get("token_usage"))
            generation = await crud.save_generation(
                db, generation_type="mcq", request_hash=request_hash, request_params=params,
                content={"questions": result["questions"], "difficulty": result.get("difficulty", body.difficulty)},
                input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd,
            )
            await crud.link_user_generation(db, user.id, generation.id, was_cache_hit=False)
            await db.commit()
            await websocket.send_json({
                "type": "result",
                "data": {
                    "generation_id": str(generation.id),
                    "was_cache_hit": False,
                    "questions": result["questions"],
                    "difficulty": result.get("difficulty", body.difficulty),
                    "token_usage": result.get("token_usage"),
                },
            })
            await websocket.close()
            return

        # Generic: pool existing + always generate POOL_FRESH_RATIO fresh
        topic_params = {
            "subject": body.subject,
            "grade": body.grade,
            "unit": body.unit,
            "topic": body.topic,
            "difficulty": body.difficulty,
        }
        topic_hash = compute_request_hash(topic_params)

        await websocket.send_json(_prog("cache_check", 1, TOTAL, "Checking question pool…"))
        pool = await crud.get_pooled_items(db, topic_hash, "mcq", "questions")

        seen: set[str] = set()
        unique_pool: list = []
        for q in pool:
            k = q.get("question", "")
            if k not in seen:
                seen.add(k)
                unique_pool.append(q)

        max_reuse = math.floor(body.num_questions * (1 - POOL_FRESH_RATIO))
        reuse_count = min(max_reuse, len(unique_pool))
        fresh_count = body.num_questions - reuse_count

        await websocket.send_json(_prog("loading_context", 2, TOTAL, "Preparing generation…"))
        n = fresh_count
        await websocket.send_json(_prog("generating", 3, TOTAL, f"Crafting {n} new question{'s' if n != 1 else ''}…"))
        result = await jobs.submit_and_wait("generate_mcq", {
            "subject": body.subject, "grade": body.grade, "unit": body.unit, "topic": body.topic,
            "num_questions": fresh_count, "difficulty": body.difficulty,
            "note_content": None, "chat_context": None,
        })
        if result.get("error"):
            await websocket.send_json({"type": "error", "code": result["error"], "detail": str(result["error"])})
            await websocket.close()
            return

        await websocket.send_json(_prog("saving", 4, TOTAL, "Saving…"))
        input_tokens, output_tokens, cost_usd = _parse_token_usage(result.get("token_usage"))
        generation = await crud.save_generation(
            db, generation_type="mcq", request_hash=topic_hash, request_params=topic_params,
            content={"questions": result["questions"], "difficulty": result.get("difficulty", body.difficulty)},
            input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd,
        )
        await crud.link_user_generation(db, user.id, generation.id, was_cache_hit=False)
        await db.commit()

        reused = random.sample(unique_pool, reuse_count) if reuse_count > 0 else []
        all_questions = result["questions"] + reused
        random.shuffle(all_questions)

        await websocket.send_json({
            "type": "result",
            "data": {
                "generation_id": str(generation.id),
                "was_cache_hit": False,
                "questions": all_questions,
                "difficulty": result.get("difficulty", body.difficulty),
                "token_usage": result.get("token_usage"),
            },
        })
        await websocket.close()

    except WebSocketDisconnect:
        pass
    except OutOfContextError as exc:
        await websocket.send_json({"type": "error", "code": "out_of_context", "detail": exc.message})
        await websocket.close()
    except Exception:
        await websocket.send_json({"type": "error", "code": "server_error", "detail": "An unexpected error occurred."})
        await websocket.close()


@router.websocket("/generate/flashcards")
async def ws_generate_flashcards(
    websocket: WebSocket,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> None:
    await websocket.accept()
    user = await _auth_ws(websocket, token, db)
    if not user:
        return

    TOTAL = 5
    try:
        data = await websocket.receive_json()
        body = FlashcardRequest(**data)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"type": "error", "code": "invalid_input", "detail": str(exc)})
        await websocket.close()
        return

    try:
        await websocket.send_json(_prog("validating", 0, TOTAL, "Validating parameters…"))
        validate_curriculum_params(body.subject, body.grade, body.unit)

        # Contextual (note/chat grounded): exact-hash caching, items must not mix with pool
        if body.note_id or body.chat_session_id:
            params = {
                "subject": body.subject,
                "grade": body.grade,
                "unit": body.unit,
                "topic": body.topic,
                "note_id": str(body.note_id) if body.note_id else None,
                "chat_session_id": str(body.chat_session_id) if body.chat_session_id else None,
                "num_cards": body.num_cards,
                "difficulty": body.difficulty,
            }
            request_hash = compute_request_hash(params)

            await websocket.send_json(_prog("cache_check", 1, TOTAL, "Checking for cached flashcards…"))
            cached = await crud.get_cached_generation(db, request_hash, "flashcard")
            if cached:
                await crud.link_user_generation(db, user.id, cached.id, was_cache_hit=True)
                await db.commit()
                await websocket.send_json({
                    "type": "result",
                    "data": {
                        "generation_id": str(cached.id),
                        "was_cache_hit": True,
                        "flashcards": cached.content["flashcards"],
                        "difficulty": cached.content.get("difficulty", body.difficulty),
                    },
                })
                await websocket.close()
                return

            await websocket.send_json(_prog("loading_context", 2, TOTAL, "Loading curriculum context…"))
            note_content: dict | None = None
            chat_context: str | None = None
            if body.note_id:
                note_gen = await crud.get_generation_for_user(db, user.id, body.note_id, "notes")
                if not note_gen:
                    await websocket.send_json({"type": "error", "code": "not_found", "detail": "Note not found."})
                    await websocket.close()
                    return
                note_content = note_gen.content.get("notes")
            if body.chat_session_id:
                chat_session = await crud.get_chat_session_with_messages(db, body.chat_session_id, user.id)
                if not chat_session:
                    await websocket.send_json({"type": "error", "code": "not_found", "detail": "Chat session not found."})
                    await websocket.close()
                    return
                chat_context = _format_chat_context(chat_session.messages)

            n = body.num_cards
            await websocket.send_json(_prog("generating", 3, TOTAL, f"Creating {n} flashcard{'s' if n != 1 else ''}…"))
            result = await jobs.submit_and_wait("generate_flashcards", {
                "subject": body.subject, "grade": body.grade, "unit": body.unit, "topic": body.topic,
                "num_cards": body.num_cards, "difficulty": body.difficulty,
                "note_content": note_content, "chat_context": chat_context,
            })
            if result.get("error"):
                await websocket.send_json({"type": "error", "code": result["error"], "detail": str(result["error"])})
                await websocket.close()
                return

            await websocket.send_json(_prog("saving", 4, TOTAL, "Saving…"))
            input_tokens, output_tokens, cost_usd = _parse_token_usage(result.get("token_usage"))
            generation = await crud.save_generation(
                db, generation_type="flashcard", request_hash=request_hash, request_params=params,
                content={"flashcards": result["flashcards"], "difficulty": result.get("difficulty", body.difficulty)},
                input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd,
            )
            await crud.link_user_generation(db, user.id, generation.id, was_cache_hit=False)
            await db.commit()
            await websocket.send_json({
                "type": "result",
                "data": {
                    "generation_id": str(generation.id),
                    "was_cache_hit": False,
                    "flashcards": result["flashcards"],
                    "difficulty": result.get("difficulty", body.difficulty),
                    "token_usage": result.get("token_usage"),
                },
            })
            await websocket.close()
            return

        # Generic: pool existing + always generate POOL_FRESH_RATIO fresh
        topic_params = {
            "subject": body.subject,
            "grade": body.grade,
            "unit": body.unit,
            "topic": body.topic,
            "difficulty": body.difficulty,
        }
        topic_hash = compute_request_hash(topic_params)

        await websocket.send_json(_prog("cache_check", 1, TOTAL, "Checking flashcard pool…"))
        pool = await crud.get_pooled_items(db, topic_hash, "flashcard", "flashcards")

        seen: set[str] = set()
        unique_pool: list = []
        for card in pool:
            k = card.get("front", "")
            if k not in seen:
                seen.add(k)
                unique_pool.append(card)

        max_reuse = math.floor(body.num_cards * (1 - POOL_FRESH_RATIO))
        reuse_count = min(max_reuse, len(unique_pool))
        fresh_count = body.num_cards - reuse_count

        await websocket.send_json(_prog("loading_context", 2, TOTAL, "Preparing generation…"))
        n = fresh_count
        await websocket.send_json(_prog("generating", 3, TOTAL, f"Creating {n} new flashcard{'s' if n != 1 else ''}…"))
        result = await jobs.submit_and_wait("generate_flashcards", {
            "subject": body.subject, "grade": body.grade, "unit": body.unit, "topic": body.topic,
            "num_cards": fresh_count, "difficulty": body.difficulty,
            "note_content": None, "chat_context": None,
        })
        if result.get("error"):
            await websocket.send_json({"type": "error", "code": result["error"], "detail": str(result["error"])})
            await websocket.close()
            return

        await websocket.send_json(_prog("saving", 4, TOTAL, "Saving…"))
        input_tokens, output_tokens, cost_usd = _parse_token_usage(result.get("token_usage"))
        generation = await crud.save_generation(
            db, generation_type="flashcard", request_hash=topic_hash, request_params=topic_params,
            content={"flashcards": result["flashcards"], "difficulty": result.get("difficulty", body.difficulty)},
            input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd,
        )
        await crud.link_user_generation(db, user.id, generation.id, was_cache_hit=False)
        await db.commit()

        reused = random.sample(unique_pool, reuse_count) if reuse_count > 0 else []
        all_cards = result["flashcards"] + reused
        random.shuffle(all_cards)

        await websocket.send_json({
            "type": "result",
            "data": {
                "generation_id": str(generation.id),
                "was_cache_hit": False,
                "flashcards": all_cards,
                "difficulty": result.get("difficulty", body.difficulty),
                "token_usage": result.get("token_usage"),
            },
        })
        await websocket.close()

    except WebSocketDisconnect:
        pass
    except OutOfContextError as exc:
        await websocket.send_json({"type": "error", "code": "out_of_context", "detail": exc.message})
        await websocket.close()
    except Exception:
        await websocket.send_json({"type": "error", "code": "server_error", "detail": "An unexpected error occurred."})
        await websocket.close()
