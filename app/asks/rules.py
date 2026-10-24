"""role_class -> (ask_type, attachment), plus promise fulfilment. OWNER: Person A. Keep this a table, not a framework."""
import re

from app.config import settings

# ask_type: what we're asking for. attachment: URL we include, or None.
RULES: dict[str, tuple[str, str | None]] = {
    "recruiter": ("resume", settings.RESUME_URL),
    "founder": ("coffee_partnership", settings.DECK_URL),
    "investor": ("update", settings.DECK_URL),
    "pm_design": ("feedback_collab", settings.DEMO_URL),
    "other": ("thank_you", None),  # TODO(A): not in the spec table; a plain thank-you keeps the door open
}


def pick(role_class: str, has_matching_job: bool) -> tuple[str, str | None]:
    """Engineers get a referral ask only when their company has a role matching our skills."""
    if role_class == "engineer":
        return ("referral", settings.RESUME_URL) if has_matching_job else ("technical_followup", None)
    return RULES.get(role_class, RULES["other"])


def asset_link(promise_text: str) -> str | None:
    """Find the link for something we promised, by keyword. resume/deck/demo are built in; ASSET_LINKS adds more."""
    links = {"resume": settings.RESUME_URL, "cv": settings.RESUME_URL, "deck": settings.DECK_URL, "demo": settings.DEMO_URL}
    links.update({k.strip().lower(): v.strip() for k, v in settings.ASSET_LINKS.items()})
    text = promise_text.lower()
    for keyword, url in links.items():
        if re.search(rf"\b{re.escape(keyword)}\b", text):
            return url
    return None


def fulfilment_line(promise_text: str) -> str:
    """'Send my CUDA benchmark repo' -> 'As promised, here's my CUDA benchmark repo: <url>'."""
    thing = re.sub(r"^(send|share|forward|email)\s+(over\s+|you\s+|her\s+|him\s+|them\s+)?", "", promise_text.strip(), flags=re.I)
    thing = re.sub(r"\s+(by|before|on|this|next)\s+\w+$", "", thing, flags=re.I).rstrip(".")
    if not re.match(r"^(my|the|our|a|an)\b", thing, flags=re.I):
        thing = f"my {thing}"
    url = asset_link(promise_text)
    if url:
        return f"As promised, here's {thing}: {url}"
    return f"As promised, I'll send {thing} over separately."
