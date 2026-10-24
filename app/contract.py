"""
FROZEN — shared contract between ingest/asks (Person A) and graph (Person B).
Change only with both owners present. Everything crossing the A/B seam is one of these models.
"""
from typing import Literal

from pydantic import BaseModel, Field

RoleClass = Literal["engineer", "recruiter", "founder", "investor", "pm_design", "other"]
DocKind = Literal["blog", "news", "repo", "job", "site"]
DraftStatus = Literal["pending", "sent", "skipped"]


class Person(BaseModel):
    name: str
    role: str | None = None
    role_class: RoleClass = "other"
    email: str | None = None


class Company(BaseModel):
    name: str
    domain: str | None = None


class Promise(BaseModel):
    by: Literal["me", "them"]
    text: str


class SessionExtract(BaseModel):
    session_id: str
    started_at: str
    transcript: str
    summary: str
    person: Person
    company: Company | None = None
    topics: list[str] = Field(default_factory=list)
    promises: list[Promise] = Field(default_factory=list)


class WebDoc(BaseModel):
    url: str
    title: str
    kind: DocKind
    published_at: str | None = None
    topics: list[str] = Field(default_factory=list)


class Job(BaseModel):
    title: str
    url: str
    req_id: str | None = None
    skills: list[str] = Field(default_factory=list)


class EnrichResult(BaseModel):
    company: str
    domain: str | None = None
    sector: str | None = None
    stage: str | None = None
    webdocs: list[WebDoc] = Field(default_factory=list)
    jobs: list[Job] = Field(default_factory=list)


class CommonGround(BaseModel):
    person: str
    company: str
    topic: str
    doc_title: str
    doc_url: str
    doc_kind: str


class Draft(BaseModel):
    id: str
    person: str
    email: str | None = None
    ask_type: str
    subject: str
    body: str
    status: DraftStatus = "pending"
    because: list[str] = Field(default_factory=list)  # URLs / topic names / job titles / promise texts
