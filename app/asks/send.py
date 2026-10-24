"""Email via Resend. OWNER: Person A. Mock mode (or missing key) logs instead of sending."""
from app.config import settings
from app.contract import Draft


def send(d: Draft) -> dict:
    if settings.MOCK_MODE or not settings.RESEND_API_KEY:
        print(f"[send:mock] to={d.email} subject={d.subject!r}\n{d.body}\n")
        return {"mock": True, "to": d.email}
    if not d.email:
        raise ValueError(f"{d.person} has no email on file")
    import resend

    resend.api_key = settings.RESEND_API_KEY
    res = resend.Emails.send({"from": settings.FROM_EMAIL, "to": [d.email], "subject": d.subject, "text": d.body})
    return {"mock": False, "to": d.email, "id": res.get("id") if isinstance(res, dict) else str(res)}
