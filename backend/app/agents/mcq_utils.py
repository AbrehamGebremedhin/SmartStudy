import random
import re
from typing import Dict, List


# Contexts where a bare capital letter A-D denotes an answer option.
# After answer positions are reshuffled these references must be remapped.
LETTER_REF_PATTERN = re.compile(
    r'(?:option|options|choice|choices|answer|meaning|sentence|version|statement|letter)\s+([A-D])\b'
    r'|\b(?:answer|correct\s+answer)\s+is\s+([A-D])\b'
    r'|\b(?:only|both|neither|either)\s+([A-D])\b'
    r'|(?:Thus|Hence|Therefore|So),?\s+([A-D])\b'
    r'|\b([A-D])(?=\s+(?:is|are|was|were)\s+(?:correct|incorrect|right|wrong|the\b))'
    r'|\b([A-D])(?=\s+corrects?\b)',
    re.IGNORECASE,
)

# Options whose text refers to other options by letter cannot be safely reshuffled.
SELF_REF_OPTION = re.compile(
    r'\b(?:both|neither|either|options?|choices?)\b.*\b(?-i:[A-D])\b'
    r'|\b(?:all|none)\s+of\s+the\s+above\b'
    r'|\b(?-i:[A-D])\s+(?:and|or|nor)\s+(?-i:[A-D])\b',
    re.IGNORECASE,
)

# Test-prep / exam-meta artifacts from SAT/English prep PDFs.
# Content matching these describes the test itself, not the skill being tested.
TEST_PREP_ARTIFACT = re.compile(
    r'\bpassage evidence\b'
    r'|\b(?:acronym|mnemonic)\b'
    r'|\bscoring\s+(?:rubric|guide|level|band)\b'
    r'|\blevel\s+\d+\s+essay\b'
    r'|\bessay\s+(?:score|scoring|level|band|rubric)\b'
    r'|\bpassage\s+types?\b'
    r'|\bquestion\s+categor(?:y|ies)\b'
    r'|\btest\s+section'
    r'|\breading\s+pace\b'
    r'|\bwords?\s+per\s+minute\b'
    r'|\bsteps?\s+to\s+(?:solve|solving|approach|tackle|answer)\b'
    r'|\b(?:test|exam)[\s-]*taking\s+(?:strateg|tip|trick)'
    r'|\b(?:study|solving|reading)\s+(?:strateg|plan|technique|method)\b'
    r'|\bhow\s+to\s+(?:study|approach|tackle|read)\b'
    r'|\bin\s+the\s+passage\b'
    r'|\bthe\s+passage\s+(?:says|states|describes|compares|mentions|refers)\b'
    r'|\baccording\s+to\s+the\s+passage\b',
    re.IGNORECASE,
)


def is_test_prep_artifact(subject: str, *texts: str) -> bool:
    """True if any text looks like exam-meta / test-prep material (SAT/English only)."""
    if subject.lower() not in ("sat", "english"):
        return False
    return any(t and TEST_PREP_ARTIFACT.search(str(t)) for t in texts)


def swap_letter_refs(text: str, letter_a: str, letter_b: str) -> str:
    """Swap option-letter references between letter_a and letter_b in explanation text."""
    if not text or letter_a == letter_b:
        return text
    sentinel = {letter_a: f"\x00{letter_a}\x00", letter_b: f"\x00{letter_b}\x00"}

    def replace(m: re.Match) -> str:
        letter = next(g for g in m.groups() if g is not None)
        if letter in (letter_a, letter_b):
            other = letter_b if letter == letter_a else letter_a
            return m.group(0)[:-1] + sentinel[other]
        return m.group(0)

    swapped = LETTER_REF_PATTERN.sub(replace, text)
    return swapped.replace(sentinel[letter_a], letter_a).replace(sentinel[letter_b], letter_b)


def redistribute_answer_positions(questions: List[Dict]) -> List[Dict]:
    """
    Physically reorder options arrays so correct answers are spread across A/B/C/D.
    Content is never changed — only which letter label the correct option receives.
    """
    n = len(questions)
    if n == 0:
        return questions

    base = n // 4
    targets = []
    for letter in ["A", "B", "C", "D"]:
        targets.extend([letter] * base)
    for letter in ["A", "B", "C", "D"][: n % 4]:
        targets.append(letter)
    random.shuffle(targets)

    result = []
    for q, target in zip(questions, targets):
        current = q.get("correct_answer", "A")
        if current == target:
            result.append(q)
            continue

        options = list(q.get("options", []))
        if any(SELF_REF_OPTION.search(str(opt)) for opt in options):
            result.append(q)
            continue

        content: Dict[str, str] = {}
        for opt in options:
            if len(opt) >= 3 and opt[1] == ")":
                content[opt[0]] = opt[3:]
        if len(content) != 4:
            result.append(q)
            continue

        content[current], content[target] = content[target], content[current]
        new_options = [f"{l}) {content[l]}" for l in ["A", "B", "C", "D"]]

        old_inc = dict(q.get("incorrect_explanations", {}))
        new_inc: Dict[str, str] = {}
        for key, explanation in old_inc.items():
            new_inc[current if key == target else key] = explanation

        q = dict(q)
        q["options"] = new_options
        q["correct_answer"] = target
        q["incorrect_explanations"] = new_inc
        q["correct_explanations"] = [
            swap_letter_refs(e, current, target) if isinstance(e, str) else e
            for e in q.get("correct_explanations", [])
        ]
        q["incorrect_explanations"] = {
            k: swap_letter_refs(v, current, target) if isinstance(v, str) else v
            for k, v in q["incorrect_explanations"].items()
        }

        result.append(q)

    return result
