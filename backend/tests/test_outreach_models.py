"""Reach out：联系人、消息两张表与 referred 状态。"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError


def make_job(s, company="Example Robotics", title="Backend Engineer"):
    from app.models import Company, Job

    c = s.scalar(select(Company).where(Company.normalized_name == company.lower()))
    if c is None:
        c = Company(display_name=company, normalized_name=company.lower())
        s.add(c)
        s.flush()
    j = Job(
        company_id=c.id,
        canonical_key=str(uuid.uuid4()),
        title=title,
        work_mode="remote",
        employment_type="full_time",
        sponsorship_policy="unclear",
        status="active",
    )
    s.add(j)
    s.flush()
    return j


def test_referred_status_allowed(db_session):
    from app.models import Application, ApplicationEvent

    job = make_job(db_session)
    app = Application(job_id=job.id, status="referred")
    db_session.add(app)
    db_session.flush()
    db_session.add(ApplicationEvent(application_id=app.id, from_status=None, to_status="referred"))
    db_session.flush()


def test_contact_linkedin_url_unique(db_session):
    from app.models import Contact

    db_session.add_all([Contact(full_name="A", found_via="user"), Contact(full_name="B", found_via="user")])
    db_session.flush()
    url = "https://www.linkedin.com/in/jane-doe"
    db_session.add(Contact(full_name="Jane", linkedin_url=url, found_via="user"))
    db_session.flush()
    db_session.add(Contact(full_name="Jane again", linkedin_url=url, found_via="user"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_message_cascade_on_contact_delete(db_session):
    from app.models import Contact, OutreachMessage

    job = make_job(db_session)
    c = Contact(full_name="Jane", found_via="user")
    db_session.add(c)
    db_session.flush()
    m = OutreachMessage(contact_id=c.id, job_id=job.id, direction="out", channel="connect_note", body="Hi")
    db_session.add(m)
    db_session.flush()
    assert m.sent_at is not None

    db_session.delete(job)
    db_session.flush()
    db_session.expire_all()
    assert db_session.get(OutreachMessage, m.id).job_id is None

    db_session.delete(db_session.get(Contact, c.id))
    db_session.flush()
    assert db_session.scalar(select(OutreachMessage).where(OutreachMessage.id == m.id)) is None


def test_source_stats_count_referred(db_session):
    from app.models import Application, JobSource

    job = make_job(db_session)
    db_session.add(JobSource(job_id=job.id, site_id="linkedin", url="https://www.linkedin.com/jobs/view/1"))
    db_session.add(Application(job_id=job.id, status="referred"))
    db_session.flush()
    row = db_session.execute(text("SELECT applied FROM v_source_stats WHERE site_id = 'linkedin'")).one()
    assert row.applied == 1
