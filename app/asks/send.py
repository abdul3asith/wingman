"""Email via Resend. OWNER: Person A. Mock mode (or missing key) logs instead of sending.
SEND_TEST_TO redirects every email to one address for rehearsals."""
from app.config import settings
from app.contract import Draft


def send(d: Draft) -> dict:
    to = settings.SEND_TEST_TO or d.email
    if settings.MOCK_MODE or not settings.RESEND_API_KEY:
        print(f"[send:mock] to={to} subject={d.subject!r}\n{d.body}\n")
        return {"mock": True, "to": to}
    if not to:
        raise ValueError(f"{d.person} has no email on file — add one in the queue before approving")
    import resend

    resend.api_key = settings.RESEND_API_KEY
    subject = f"[test → {d.email}] {d.subject}" if settings.SEND_TEST_TO else d.subject
    res = resend.Emails.send({"from": settings.FROM_EMAIL, "to": [to], "subject": subject, "text": d.body})
    print(f"[send] to={to} id={res.get('id') if isinstance(res, dict) else res}")
    return {"mock": False, "to": to, "id": res.get("id") if isinstance(res, dict) else str(res)}
