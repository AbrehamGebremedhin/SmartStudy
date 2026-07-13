# SmartStudy — System Documentation

How the system fits together. For setup and API tables see the [README](../README.md).

## High-Level Architecture

```
┌─────────────────────┐         ┌──────────────────────────────────────┐
│  React SPA (Vite)   │  HTTP   │  FastAPI backend                     │
│  PWA + offline shell│────────▶│  /api/*  (REST + WebSocket)          │
│                     │   WS    │                                      │
└─────────────────────┘         │  routes → services → agents → LLMs   │
                                └──────┬───────────┬───────────┬───────┘
                                       │           │           │
                                 PostgreSQL     Milvus      DeepSeek /
                                 (asyncpg)   (+ Ollama      Gemini
                                              embeddings)   (LangChain)
```

## Backend Layers

Request path: `api/routes` → `services` → `agents` → LLM/DB.

| Layer | Location | Responsibility |
|---|---|---|
| Routes | `backend/app/api/routes/` | HTTP/WS handlers, auth deps, request validation |
| Services | `backend/app/services/` | Job queue, generation orchestration, caching, spaced repetition |
| Agents | `backend/app/agents/` | LLM pipeline: retrieval, refinement, generation, validation |
| DB | `backend/app/db/` | SQLAlchemy models, CRUD, session management |
| Auth | `backend/app/auth/` | Google OAuth verification, JWT issue/verify |
| Security | `backend/app/security/` | Rate limiting, input/output sanitization, headers, audit log |
| Core | `backend/app/core/` | Curriculum validation, exception types |

## Content Generation Pipeline

Every generation (MCQ, flashcards, notes) runs through the same agent chain:

```
request ──▶ cache check (services/cache.py) ── hit ──▶ return cached
              │ miss
              ▼
        job queue (services/jobs.py)
              ▼
        RetrievalAgent ─── Milvus vector search over curriculum docs
              ▼
        ContextRefinementAgent ─── trims/reranks retrieved context
              ▼
        GenerationAgent ─── DeepSeek via LangChain (per-type mixins:
              │              mcq.py, flashcards.py, notes.py, chat.py,
              │              evaluation.py)
              ▼
        ValidationAgent ─── second-model check for curriculum fit,
              │              correctness, and coverage; failures retried
              ▼
        persist Generation + return
```

- **Job queue** (`services/jobs.py`): DB-backed queue with worker pool, supervisor, retry with backoff, and a reaper for stuck jobs. Waiters are woken by an event, not DB polling. Routes call `submit_and_wait`; WebSocket clients (`routes/ws.py`) stream progress.
- **Caching** (`services/cache.py`): identical (subject, grade, unit, type, params) requests return the stored generation — no LLM call.
- **Curriculum validation** (`core/curriculum_validation.py`): rejects out-of-scope subject/grade/unit combos before any LLM spend. `agents/subject_rules.py` adds per-subject generation rules.
- **Gemini pool** (`agents/gemini_pool.py`): rotates Gemini API keys for validation-side calls.

## AI Tutor Chat

`agents/chat.py` + `agents/session_manager.py`. Sessions live in Postgres (`ChatSession`, `ChatMessage`) with a TTL (`CHAT_SESSION_TTL_HOURS`). Responses stream over WebSocket, are scope-checked (`ValidationAgent.check_chat_scope`) so the tutor stays on-curriculum, and closed chats are distilled into `ChatActivity` rows that feed analytics.

## Past Exams / Mock Exams

`ExamQuestion` holds scraped EUEE questions (enriched offline by an LLM pipeline). `routes/exam.py` serves them by subject/year — no generation cost, real exam content.

## Learning Loop

- **Attempts** (`routes/analytics.py`, `QuestionAttempt`): every answered question is logged with a `source` (practice, exam, review, drill…). Review/drill attempts are *excluded* from mastery so re-practice doesn't inflate scores.
- **Mistake bank** (`routes/mistakes.py`, `Mistake`): wrong answers are re-served until answered correctly; `/mistakes/count` powers the nav badge.
- **Bookmarks** (`routes/bookmarks.py`): save any question for later.
- **Spaced repetition** (`services/srs.py`, `FlashcardReview`): Leitner boxes schedule flashcard reviews.
- **Analytics**: per-unit mastery, daily trends (Addis Ababa timezone), and retention curves, rendered as charts on the frontend. Product analytics via PostHog.

## Auth & Security

1. Frontend obtains a Google ID token → `POST /api/auth/login`.
2. Backend verifies it (`auth/google.py`), upserts the `User`, and issues its own JWT (`auth/tokens.py`, expiry `APP_TOKEN_EXPIRE_DAYS`).
3. All authed routes take the JWT via dependency in `api/deps.py`.

Defense layers in `security/`: SlowAPI rate limits (200 generations/day, 10/min), input sanitization before prompts, output sanitization after LLM responses, security headers middleware, and `SecurityEvent` audit logging.

## Data Model (main tables)

| Table | Purpose |
|---|---|
| `User` | Google-authenticated users |
| `Generation` / `UserGeneration` | Cached AI content + per-user history link |
| `ExamQuestion` | Enriched past EUEE questions |
| `Job` | Async generation job queue |
| `QuestionAttempt` | Source-tagged answer log (analytics) |
| `Mistake` / `Bookmark` | Mistake bank, saved questions |
| `FlashcardReview` | Leitner spaced-repetition state |
| `UserProgress` | XP / gamification progress |
| `ChatSession` / `ChatMessage` / `ChatActivity` | Tutor chat + distilled analytics context |
| `SecurityEvent` | Audit log |

Migrations via Alembic.

## Frontend

React 18 SPA. Pages map 1:1 to features (`MCQ`, `Flashcards`, `Notes`, `Chat`, `MockExam`, `Review`, `History`, `Home`). Each backend feature has a matching wrapper in `src/services/*.service.js` over a shared `apiClient.js`. `useGenerationWS` hook handles WebSocket streaming. Gamification (XP, levels, streaks, achievements — `ss_gamify_v1` in localStorage) is awarded only through its handler layer. Dark mode and PWA installability are built in.
