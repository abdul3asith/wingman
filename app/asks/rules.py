"""role_class -> (ask_type, attachment). OWNER: Person A. Keep this a table, not a framework."""
from app.config import settings

# ask_type: what we're asking for. attachment: URL we include (resume / deck) or None.
RULES: dict[str, tuple[str, str | None]] = {
    "recruiter": ("resume", settings.RESUME_URL),
    "founder": ("collab", settings.DECK_URL),
    "investor": ("deck", settings.DECK_URL),
    "pm_design": ("feedback_call", None),
    "other": ("thank_you", None),
}


def pick(role_class: str, has_matching_job: bool) -> tuple[str, str | None]:
    """Engineers get a referral ask only when their company has a role matching our skills."""
    if role_class == "engineer":
        return ("referral", settings.RESUME_URL) if has_matching_job else ("intro_chat", None)
    return RULES.get(role_class, RULES["other"])
