"""邮件同步的资料表：事件来源预设、email 来源网站。"""

from app.models import Application, ApplicationEvent, Company, Job, JobSite


def _job(db):
    c = Company(display_name="Northwind Labs", normalized_name="northwind labs")
    db.add(c)
    db.flush()
    job = Job(
        company_id=c.id,
        canonical_key="k1",
        title="Backend Engineer",
        work_mode="unknown",
        employment_type="unknown",
        sponsorship_policy="unclear",
        status="unverified",
        verification_source="email",
    )
    db.add(job)
    db.flush()
    return job


def test_event_source_defaults_user(db_session):
    app = Application(job_id=_job(db_session).id, status="saved")
    db_session.add(app)
    db_session.flush()
    ev = ApplicationEvent(application_id=app.id, to_status="saved")
    db_session.add(ev)
    db_session.flush()
    db_session.refresh(ev)
    assert ev.source == "user" and ev.email_message_id is None


def test_email_site_seeded(db_session):
    assert db_session.get(JobSite, "email").access_method == "paste_only"


def test_email_site_not_in_search_list(client):
    ids = [s["id"] for s in client.get("/api/job-sites").json()]
    assert "email" not in ids and "manual" not in ids and ids
