# SmartStudy

An AI-powered study companion built for Ethiopian high school students (grades 9–12) and EUEE exam preparation. SmartStudy generates curriculum-aligned MCQs, flashcards, and study notes, provides a real-time AI tutor chat, and motivates learners through a gamification system rooted in Ethiopian academic tradition.

---

## Features

- **MCQ Practice** — Generate exam-style multiple-choice questions with AI-written solutions
- **Flashcards** — Create spaced-repetition decks from any curriculum topic
- **Study Notes** — AI-generated comprehensive notes with worked examples
- **AI Tutor Chat** — Real-time conversation for concept clarification (WebSocket streaming)
- **Answer Evaluation** — Submit written answers and receive LLM-graded feedback
- **Content Caching** — Identical requests return cached results instantly (no wasted tokens)
- **Gamification** — XP, levels, streaks, and achievements using eight Ethiopian academic ranks (Temari → Liqe Liqawnt)
- **Curriculum Validation** — Enforces Ethiopian curriculum scope (specific subjects, grades, and units)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, React Router 6, Vite 5 |
| Backend | Python 3.13, FastAPI, SQLAlchemy 2 (async) |
| Database | PostgreSQL (asyncpg) |
| Vector Search | Milvus + Ollama embeddings |
| LLM | DeepSeek (`deepseek-v4-flash`) via LangChain |
| Auth | Google OAuth 2.0 + JWT |
| Rate Limiting | SlowAPI |
| Migrations | Alembic |

---

## Project Structure

```
SmartStudy/
├── frontend/               # React + Vite SPA
│   ├── src/
│   │   ├── pages/          # MCQ, Flashcards, Notes, Chat, History, Home
│   │   ├── components/     # Sidebar, GamifyLayer, ActivityHeatmap, etc.
│   │   ├── services/       # API client wrappers per feature
│   │   ├── hooks/          # useGenerationWS (WebSocket streaming)
│   │   └── utils/          # curriculum metadata, XP logic, localStorage cache
│   └── package.json
│
└── backend/                # FastAPI application
    ├── app/
    │   ├── agents/         # AI orchestration (generation, retrieval, validation)
    │   ├── services/       # Business logic, caching, evaluation
    │   ├── db/             # SQLAlchemy models, CRUD, DB init
    │   ├── auth/           # Google OAuth, JWT tokens
    │   ├── security/       # Rate limiting, input/output sanitization, audit log
    │   ├── core/           # Curriculum validation, custom exceptions
    │   ├── schemas/        # Pydantic request/response models
    │   ├── routers/        # FastAPI route handlers
    │   └── config.py       # Validated settings (pydantic-settings)
    ├── tests/              # Unit, integration, and E2E tests
    └── pyproject.toml
```

---

## Getting Started

### Prerequisites

- Python 3.13
- Node.js 18+
- PostgreSQL database
- Milvus vector database (for RAG retrieval)
- [uv](https://github.com/astral-sh/uv) (recommended for Python deps)

### Backend Setup

```bash
cd backend

# Install dependencies
uv sync
# or: pip install -e ".[dev]"

# Copy and fill in environment variables
cp .env.example .env

# Start the API server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Copy and fill in environment variables
cp .env.example .env

# Start the dev server (proxies /api to :8000)
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Description |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API key (`sk-...`) |
| `DATABASE_URL` | PostgreSQL connection string (`postgresql+asyncpg://user:pass@host:port/db`) |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID (`...apps.googleusercontent.com`) |
| `SECRET_KEY` | JWT signing secret |
| `CHAT_SESSION_TTL_HOURS` | Session expiry in hours (default: `24`) |
| `APP_TOKEN_EXPIRE_DAYS` | JWT expiry in days (default: `30`) |

### Frontend (`frontend/.env`)

| Variable | Description |
|---|---|
| `VITE_GOOGLE_CLIENT_ID` | Google OAuth client ID (same as backend) |

---

## API Overview

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/auth/login` | Google OAuth token exchange |
| `POST` | `/mcq/generate` | Generate MCQ questions |
| `POST` | `/flashcards/generate` | Generate flashcard deck |
| `POST` | `/notes/generate` | Generate study notes |
| `POST` | `/evaluate` | Evaluate a written answer |
| `POST` | `/chat/sessions` | Create chat session |
| `GET/POST` | `/chat/sessions/{id}` | Get session or add message |
| `GET` | `/history/{type}` | Fetch generation history |
| `WS` | `/ws/generate/{type}` | Streaming generation progress |
| `GET` | `/health` | Health check |

Rate limits: 200 generations/day, 10/minute per user.

---

## Running Tests

```bash
cd backend

# All tests
pytest tests/

# With coverage report
pytest tests/ --cov=app

# Only unit tests (no I/O)
pytest -m unit

# Only integration tests
pytest -m integration
```

Tests use `testcontainers` to spin up an isolated PostgreSQL instance — no manual DB setup required.

---

## Supported Curriculum

- **Grades:** 9, 10, 11, 12, and EUEE preparation
- **Subjects:** Biology, Chemistry, Physics, Mathematics, English, Civics, Economics, Geography, History, Business, SAT
- Content generation is scoped to the Ethiopian national curriculum by unit and grade level.
