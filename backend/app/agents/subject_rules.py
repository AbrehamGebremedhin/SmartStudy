STEM_SUBJECTS = ["maths", "physics", "chemistry", "biology", "economics"]
HUMANITIES_SUBJECTS = ["english", "history", "geography", "civics", "general_business"]


def get_subject_rules(subject: str) -> str:
    if subject.lower() == "biology":
        return """
                - The questions with workout questions should contain workout steps
                - Use ^ in place of superscript and _ in place of subscript
                - Include step-by-step solutions where applicable
                BIOCHEMICAL ACCURACY RULES (apply to ALL explanations, not just the answer):
                - Electron transport chain: Complexes I, III, and IV pump protons across the inner
                  mitochondrial membrane. Complex II does NOT pump protons — never state otherwise.
                - Cofactor directionality: always name the cofactor as it exists at the START of
                  the reaction. Catabolic (oxidation) reactions consume NADH and produce NAD+;
                  do not write "NAD+ is used" for a reaction that oxidises NADH.
                - Phosphate transfer: direct phosphate transfer DOES occur in substrate-level
                  phosphorylation and coupled reactions (e.g., creatine kinase). Never write
                  "direct phosphate transfer does not occur" for these reactions.
                - When writing incorrect_explanations, verify that the reason given for an option
                  being wrong is itself biochemically accurate. A wrong-option explanation must
                  not teach incorrect biology while trying to dismiss the wrong choice.
            """
    if subject.lower() in STEM_SUBJECTS:
        return """
                - The questions with workout questions should contain workout steps
                - Use ^ in place of superscript and _ in place of subscript
                - Include step-by-step solutions where applicable
            """
    elif subject.lower() in HUMANITIES_SUBJECTS:
        return """
                - No essay or paragraph-based questions
                - Focus on clear, concise factual questions
                - Include relevant historical/contextual references
            """
    elif subject.lower() == "sat":
        return """
                - Scholastic Aptitude Test: about 80% verbal reasoning, 20% quantitative/maths
                - Verbal: analogies, synonyms, antonyms, word substitution, classification,
                  sentence correction, reading comprehension, logical reasoning
                - Quantitative: arithmetic, percentages, ratios, averages, basic algebra,
                  number properties, data interpretation, basic geometry (with workout steps)
                - Never generate questions about test-taking strategies or scoring rubrics
            """
    return "- General format rules apply"


def get_mcq_subject_guidance(subject: str) -> str:
    """Extra MCQ-only guidance modelled on the actual EUEE exam format."""
    s = subject.lower()
    if s == "english":
        return """
                ENGLISH = EUEE ENGLISH (READING-COMPREHENSION HEAVY):
                Target mix: about 75% reading-based questions and 25% grammar/usage questions.

                READING-BASED QUESTIONS (the majority — roughly 3 of every 4):
                - Each MUST include a SHORT self-contained passage (4-8 sentences) in the
                  `passage` field, then ask ONE question about it. Vary the type across the set:
                  * Main idea / true-according-to-passage: "Which statement is true according to
                    the passage?" or "What is the main idea of the passage?"
                  * Inference: what the passage implies but does not state outright.
                  * Reference: "What does the word 'there'/'it'/'they'/'this' refer to in the
                    passage?" (the referenced word must actually appear in the passage).
                  * Vocabulary-in-context: "Which is closest in meaning to 'haggard' as used in
                    the passage?" — the target word MUST appear verbatim in the passage.
                - You write the passage yourself; make it coherent and self-contained. It need
                  not be copied from the source. Several reading questions may not share a passage
                  unless you intend them to — each carries its own passage.

                GRAMMAR / USAGE QUESTIONS (the minority — roughly 1 of every 4, passage = null):
                - Put a complete example sentence in the stem and test tense, subject-verb
                  agreement, conditionals, tag questions, sentence structure, modifiers,
                  prepositions, etc. Each option is a full candidate sentence or phrase.
                  e.g. "Which sentence correctly uses the present perfect tense?"

                FORBIDDEN: memorised lists, exercise layouts, "column A/B", answer keys, or any
                test-administration fact. Never reference material the student cannot see.
            """
    if s == "sat":
        return """
                SAT = SCHOLASTIC APTITUDE TEST (~80% VERBAL REASONING + ~20% QUANTITATIVE):
                Target mix per set: about 4 of every 5 questions VERBAL aptitude, and about
                1 of every 5 questions QUANTITATIVE/MATH reasoning. Each is a standalone
                4-option question; vary the types across the set.

                VERBAL APTITUDE (~80%, the majority):
                - Analogy: "KEY is to LOCK as ____ is to COMPUTER" (options complete the same
                  relationship, e.g. PASSWORD). Name the relationship in the explanation.
                - Synonym: "Which word is closest in meaning to PHONEY?" (e.g. Fake).
                - Antonym: "Which word is most nearly OPPOSITE in meaning to <word>?".
                - Word substitution: give a short definition/phrase, ask for the single word
                  that means it.
                - Classification (odd-one-out): four items where three share a category and one
                  does not; ask which does NOT belong.
                - Sentence correction: present a sentence and ask which version is grammatically
                  correct, or which underlined part contains the error.
                - Reading comprehension: include a SHORT self-contained passage (4-8 sentences)
                  in the `passage` field, then ask a main-idea, inference, reference, or
                  vocabulary-in-context question about it.
                - Analytical / logical reasoning: a short self-contained deduction or logic
                  puzzle answerable from the stem alone.

                QUANTITATIVE / MATH (~20%, roughly 1 in every 5 questions):
                - SAT-style problem solving: arithmetic, percentages, ratios and proportions,
                  averages, basic algebra (linear/quadratic), number properties, simple data
                  interpretation, and basic geometry.
                - Put the ENTIRE problem in the question stem (passage = null), keep it
                  self-contained, and provide a clear step-by-step solution in `workout_steps`.
                  Use ^ for superscript and _ for subscript (e.g. x^2).

                STRICTLY FORBIDDEN for SAT:
                - US-style two-blank sentence completion.
                - Questions ABOUT test-taking strategies, study methods, reading pace, scoring
                  rubrics, or exam format (e.g. "the 4Ps strategy", "the BLANKS strategy",
                  "passage evidence"). Those describe a prep book, not the exam. Test ability
                  directly.
            """
    return ""


def get_grounding_rule(subject: str) -> str:
    """How tightly generated content must stay within the retrieved source text."""
    if subject.lower() in ("sat", "english"):
        return """
                GROUNDING RULE (calibration): Use the provided context to calibrate the
                vocabulary level, topics, and difficulty to what a student at this level studies.
                You do NOT need to quote or copy the context: aptitude content (analogies,
                synonyms, antonyms, classification, reasoning, reading passages, basic maths) may
                use appropriate general vocabulary, examples and relationships rather than being
                lifted from the source. Stay within the kind of language and topics the context
                represents; do not drift into unrelated specialist material.
            """
    return """
                CONTEXT GROUNDING RULE: Every piece of generated content must be drawn
                exclusively from the provided context. You may elaborate on and clarify what the
                context contains, but do not introduce concepts, facts, examples, or details that
                do not appear in the context. If something is not in the context, do not include it.
            """


def get_subject_focus(subject: str) -> str:
    """Format-neutral description of what English/SAT content should cover."""
    s = subject.lower()
    if s == "english":
        return """
                ENGLISH FOCUS: emphasise reading and language skills — reading comprehension and
                inference, vocabulary (meaning in context, synonyms/antonyms, word formation),
                and grammar/usage (tenses, subject-verb agreement, conditionals, sentence
                structure, modifiers, tag questions, punctuation). Test the skill DIRECTLY with
                concrete language examples (e.g. "Closest in meaning to 'haggard'?", "Correct the
                subject-verb agreement in this sentence").

                STRICTLY DO NOT create content about how a test works or how to study for it:
                no exercise layouts, numbered word-lists, answer keys, "column A/B", study
                acronyms or mnemonics, or any test-administration / test-prep material. Teach the
                English skill itself, never how the exam is built.
            """
    if s == "sat":
        return """
                SAT FOCUS (Scholastic Aptitude Test): cover about 80% verbal aptitude and 20%
                quantitative — and test the ACTUAL ability directly, never how the test works.
                Verbal = vocabulary (synonyms, antonyms, word meanings, words in context),
                analogies and word relationships, classification (odd-one-out), sentence
                correction / grammar, reading and verbal reasoning, logical reasoning.
                Quantitative = arithmetic, percentages, ratios, averages, basic algebra, number
                properties, data interpretation, basic geometry.
                GOOD examples: "Synonym closest to PHONEY?", "Most nearly OPPOSITE of ALACRITY?",
                "Complete the analogy: KEY is to LOCK as ____ is to COMPUTER", "What is 30% of 80?".

                STRICTLY FORBIDDEN (these describe a prep book, not the skills being tested):
                - study acronyms or mnemonics (e.g. BLANKS, READING, the 4Ps);
                - essay scoring levels, bands or rubrics (e.g. "characteristics of a Level 6 essay");
                - lists of "passage types", "question categories" or test sections;
                - reading-pace advice, time limits, or any description of how the SAT is structured.
                Never make a card whose answer is a fact ABOUT the exam. Make cards that exercise
                vocabulary, analogies, grammar, reasoning or maths.
            """
    return ""


def presentation_rules() -> str:
    """Shared no-meta-reference rules for student-facing content (flashcards, notes)."""
    return """
                PRESENTATION RULES:
                - The student sees only this material, never the retrieval source. Never write
                  "according to the context", "based on the passage/source", "as the table / list
                  / exercise shows", and never cite exercise numbers, columns, page numbers or
                  answer keys.
                - Never include test-administration or test-prep material — scoring rubrics,
                  marking schemes, band/level descriptors, study strategies, reading-pace advice,
                  time/word/file limits. Teach the academic knowledge and skills only.
            """
