from typing import Optional

from app.core.exceptions import OutOfContextError

VALID_COMBINATIONS: dict[int, dict[str, int]] = {
    12: {
        'biology': 6, 'chemistry': 5, 'civics': 10, 'economics': 8,
        'english': 10, 'general_business': 4, 'geography': 8,
        'history': 9, 'maths': 9, 'physics': 5,
    },
    11: {
        'biology': 6, 'chemistry': 6, 'civics': 11, 'economics': 6,
        'english': 10, 'general_business': 4, 'geography': 8,
        'history': 9, 'maths': 8, 'physics': 7,
    },
    10: {
        'biology': 5, 'chemistry': 6, 'civics': 8, 'economics': 8,
        'english': 10, 'geography': 8, 'history': 9, 'maths': 7,
        'physics': 6,
    },
    9: {
        'biology': 6, 'chemistry': 5, 'civics': 8, 'economics': 7,
        'english': 12, 'geography': 8, 'history': 9, 'maths': 9,
        'physics': 7,
    },
}

# Subjects that span all grades (no grade/unit filtering applies)
CROSS_GRADE_SUBJECTS = {"sat", "english"}


def validate_curriculum_params(
    subject: str,
    grade: Optional[int],
    unit: Optional[str],
) -> None:
    """Raise OutOfContextError if grade/subject/unit combo is not in the curriculum."""
    if subject in CROSS_GRADE_SUBJECTS:
        return

    if grade is None:
        return

    if grade not in VALID_COMBINATIONS:
        raise OutOfContextError(
            f"Grade {grade} is not available. Valid grades are 9, 10, 11, and 12.",
            valid_options={"grades": [9, 10, 11, 12]},
        )

    grade_subjects = VALID_COMBINATIONS[grade]
    if subject not in grade_subjects:
        available = sorted(grade_subjects.keys())
        raise OutOfContextError(
            f"'{subject.title()}' is not offered in Grade {grade}. "
            f"Available subjects for Grade {grade}: {', '.join(available)}.",
            valid_options={"subjects": available},
        )

    if unit is not None:
        try:
            unit_num = int(unit)
        except (ValueError, TypeError):
            raise OutOfContextError(
                "Unit must be a number.",
                valid_options={},
            )
        max_units = grade_subjects[subject]
        if unit_num < 1 or unit_num > max_units:
            raise OutOfContextError(
                f"Unit {unit_num} does not exist for {subject.title()} Grade {grade}. "
                f"Valid units are 1–{max_units}.",
                valid_options={"units": list(range(1, max_units + 1))},
            )
