"""Email via Resend. OWNER: Person A. Mock mode (or missing key) logs instead of sending.
SEND_TEST_TO redirects every email to one address for rehearsals. send_at (ISO 8601) schedules via Resend."""
from app.config import settings
from app.contract import Draft


def send(d: Draft, send_at: str | None = None) -> dict:
    to = settings.SEND_TEST_TO or d.email
    when = f" scheduled_at={send_at}" if send_at else ""
    if settings.MOCK_MODE or not settings.RESEND_API_KEY:
        print(f"[send:mock] to={to}{when} subject={d.subject!r}\n{d.body}\n")
        return {"mock": True, "to": to, "scheduled_at": send_at}
    if not to:
        raise ValueError(f"{d.person} has no email on file — add one in the queue before approving")
    import resend

    resend.api_key = settings.RESEND_API_KEY
    subject = f"[test → {d.email}] {d.subject}" if settings.SEND_TEST_TO else d.subject
    params = {"from": settings.FROM_EMAIL, "to": [to], "subject": subject, "text": d.body}
    if send_at:
        params["scheduled_at"] = send_at
    res = resend.Emails.send(params)
    rid = res.get("id") if isinstance(res, dict) else str(res)
    print(f"[send] to={to}{when} id={rid}")
    return {"mock": False, "to": to, "id": rid, "scheduled_at": send_at}
