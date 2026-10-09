"""English poetic forms and the prompts used to drive the writer model.

The harness is *writer-only*: it asks a local model to compose a poem on a
user-supplied brief in a chosen form. It does not submit, test, score, or
transmit the result anywhere. These templates describe poetic structure; the
subject matter comes entirely from the caller's ``brief``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Form:
    name: str
    summary: str
    instructions: str


FORMS: dict[str, Form] = {
    "free_verse": Form(
        "free_verse",
        "Unmetered, unrhymed verse shaped by line breaks and imagery.",
        "Write in free verse: no fixed meter or rhyme. Use deliberate line "
        "breaks, concrete imagery, and rhythm from natural speech. 12-24 lines.",
    ),
    "haiku": Form(
        "haiku",
        "Three lines, 5-7-5 syllables, a seasonal or sensory turn.",
        "Write a haiku: exactly three lines of 5, 7, and 5 syllables. Favour a "
        "concrete image and a turn (kireji) between the parts.",
    ),
    "tanka": Form(
        "tanka",
        "Five lines, 5-7-5-7-7 syllables.",
        "Write a tanka: five lines of 5, 7, 5, 7, 7 syllables, pivoting after "
        "the third line from image to reflection.",
    ),
    "limerick": Form(
        "limerick",
        "Five lines, AABBA, anapestic, comic.",
        "Write a limerick: five lines rhyming AABBA, bouncing anapestic meter, "
        "lines 1/2/5 longer than 3/4, light and comic in tone.",
    ),
    "sonnet": Form(
        "sonnet",
        "14 lines, iambic pentameter, Shakespearean ABAB CDCD EFEF GG.",
        "Write a Shakespearean sonnet: 14 lines of iambic pentameter rhyming "
        "ABAB CDCD EFEF GG, with a volta near line 9 and a resolving couplet.",
    ),
    "villanelle": Form(
        "villanelle",
        "19 lines, two refrains, five tercets and a quatrain.",
        "Write a villanelle: 19 lines as five tercets then a quatrain, rhyme "
        "ABA ... ABAA. Line 1 and line 3 are refrains that alternate as the "
        "last line of each tercet and close together as the final couplet.",
    ),
    "ballad": Form(
        "ballad",
        "Quatrains, alternating tetrameter/trimeter, ABCB, narrative.",
        "Write a ballad: quatrains in alternating iambic tetrameter and "
        "trimeter, rhyming ABCB, telling a story with a strong narrative drive. "
        "4-6 stanzas.",
    ),
    "sestina": Form(
        "sestina",
        "Six sestets plus a tercet, six repeating end-words.",
        "Write a sestina: six six-line stanzas and a closing three-line envoi. "
        "Choose six end-words and permute them in the fixed sestina order; the "
        "envoi uses all six.",
    ),
    "ode": Form(
        "ode",
        "Elevated address to a subject, varied stanzas.",
        "Write an ode: an elevated, celebratory address to its subject in "
        "several stanzas, with rich figurative language and a dignified tone.",
    ),
    "acrostic": Form(
        "acrostic",
        "First letters of each line spell a word.",
        "Write an acrostic poem where the first letter of each line, read top "
        "to bottom, spells a word drawn from the brief. Keep lines coherent.",
    ),
    "blank_verse": Form(
        "blank_verse",
        "Unrhymed iambic pentameter.",
        "Write in blank verse: unrhymed iambic pentameter, 14-24 lines, with "
        "natural enjambment and a measured, meditative voice.",
    ),
    "couplet": Form(
        "couplet",
        "Rhymed pairs of lines.",
        "Write in rhymed couplets (AABB ...): 8-16 lines of closed or run-on "
        "couplets with a consistent meter.",
    ),
    "cinquain": Form(
        "cinquain",
        "Five lines, 2-4-6-8-2 syllables.",
        "Write a cinquain: five lines of 2, 4, 6, 8, and 2 syllables, building "
        "to an image and resolving on the short final line.",
    ),
}

DEFAULT_FORM = "free_verse"

# System prompt establishing the writer-only contract for the model.
SYSTEM_PROMPT = (
    "You are a poet. You compose a single poem in the requested English poetic "
    "form, on the subject the user provides. Return ONLY the poem: no title "
    "unless asked, no preamble, no commentary, no explanation, no markdown "
    "fences. Honour the form's structural rules as closely as you can."
)


def list_forms() -> list[str]:
    return sorted(FORMS)


def get_form(name: str) -> Form:
    key = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key not in FORMS:
        raise KeyError(
            f"unknown poetic form {name!r}; available: {', '.join(list_forms())}"
        )
    return FORMS[key]


def build_prompt(form_name: str, brief: str, *, title: str | None = None) -> str:
    """Compose the user-side generation prompt for a given form and brief."""
    form = get_form(form_name)
    brief = (brief or "").strip()
    if not brief:
        raise ValueError("a non-empty brief is required to generate a poem")
    parts = [
        f"Form: {form.name} — {form.summary}",
        f"Instructions: {form.instructions}",
        f"Subject / brief: {brief}",
    ]
    if title:
        parts.append(f"Give the poem the title: {title}")
    parts.append("Compose the poem now. Output the poem text only.")
    return "\n".join(parts)
