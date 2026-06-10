"""
Static response payloads used to mock GenerationAgent calls in tests.
"""

FIXTURE_MCQ_QUESTIONS = [
    {
        "topic": "Newton's Laws",
        "question": "What is the acceleration of a 5 kg object under a net force of 10 N?",
        "options": ["A) 0.5 m/s^2", "B) 2 m/s^2", "C) 5 m/s^2", "D) 50 m/s^2"],
        "correct_answer": "B",
        "passage": None,
        "workout_steps": ["F = ma", "10 = 5 x a", "a = 2 m/s^2"],
        "correct_explanations": ["By Newton's second law, a = F/m = 10/5 = 2 m/s^2"],
        "incorrect_explanations": {
            "A": "0.5 inverts the ratio",
            "C": "5 is the mass, not the acceleration",
            "D": "50 multiplies instead of divides",
        },
    }
]

FIXTURE_MCQ_RESPONSE = {
    "questions": FIXTURE_MCQ_QUESTIONS,
    "difficulty": "medium",
    "token_usage": "Input: 500 | Output: 1,200 | $0.0004",
}

FIXTURE_FLASHCARDS = [
    {
        "topic": "Newton's Laws",
        "front": "What does Newton's Second Law state?",
        "back": "F = ma: net force equals mass times acceleration",
    }
]

FIXTURE_FLASHCARD_RESPONSE = {
    "flashcards": FIXTURE_FLASHCARDS,
    "difficulty": "medium",
    "token_usage": "Input: 300 | Output: 600 | $0.0002",
}

FIXTURE_NOTES = {
    "title": "Newton's Laws of Motion",
    "overview": "Newton's three laws describe the relationship between force and motion.",
    "key_concepts": ["Inertia", "F=ma", "Action-Reaction"],
    "sections": [
        {"heading": "First Law", "content": "An object at rest stays at rest unless acted upon."},
        {"heading": "Second Law", "content": "F = ma describes how force causes acceleration."},
        {"heading": "Third Law", "content": "Every action has an equal and opposite reaction."},
    ],
}

FIXTURE_NOTES_RESPONSE = {
    "notes": FIXTURE_NOTES,
    "token_usage": "Input: 800 | Output: 2,000 | $0.0007",
}

FIXTURE_CHAT_RESPONSE = {
    "current_response": {
        "response": "Newton's second law states that F = ma, where F is force, m is mass, and a is acceleration.",
        "key_concepts": ["force", "mass", "acceleration"],
    },
    "title": "Newton's Laws Discussion",
    "token_usage": "Input: 200 | Output: 400 | $0.0001",
}

FIXTURE_EVAL_RESPONSE = {
    "is_correct": True,
    "score": 0.9,
    "feedback": "Excellent! You correctly applied Newton's second law.",
    "improvement_suggestions": ["Show all unit conversions explicitly"],
    "correct_solution": ["F = ma", "10 = 5 x a", "a = 2 m/s^2"],
    "misconceptions": [],
    "key_points_missed": [],
    "strengths": ["Correct formula", "Clear working"],
    "token_usage": "Input: 400 | Output: 800 | $0.0003",
}

FIXTURE_NOTE_CHAT_RESPONSE = {
    "answer": "ATP is produced during the light reactions of photosynthesis via photophosphorylation.",
    "key_concepts": ["ATP", "photophosphorylation", "light reactions"],
    "follow_up_questions": ["What is the role of NADPH?", "How does the Calvin cycle use ATP?"],
    "error": None,
    "token_usage": "Input: 300 | Output: 500 | $0.0002",
}

FIXTURE_EVAL_RESPONSE_WRONG = {
    "is_correct": False,
    "score": 0.2,
    "feedback": "Incorrect. You confused mass and force in the formula.",
    "improvement_suggestions": ["Review F=ma carefully", "Practice unit analysis"],
    "correct_solution": ["F = ma", "10 = 5 x a", "a = 2 m/s^2"],
    "misconceptions": ["Confused mass with acceleration"],
    "key_points_missed": ["F=ma formula application"],
    "strengths": [],
    "token_usage": "Input: 400 | Output: 800 | $0.0003",
}
