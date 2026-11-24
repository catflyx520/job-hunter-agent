import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import get_sessionmaker
from app.llm.base import LLMError
from app.materials.style import (
    LearnedRule,
    StyleError,
    active_rule_texts,
    check_rules,
    learn_style,
    norm,
    strip_placeholders,
)
from app.models import Material, StyleRule
from tests.samples import STYLE_REPLY
from tests.test_api_m2 import _ingest, _setup


def _edited(
    db,
    kind="cover_letter",
    draft="Dear team, I am excited to apply. I built APIs.",
    final="I built APIs.",
    day=1,
    **extra,
):
    """一份保存过修改的草稿；final=None 表示没改过。day 决定新旧顺序。"""
    m = Material(
        id=uuid.uuid4(),
        kind=kind,
        jd_source="none",
        status="done",
        output_text=draft,
        edited_text=final,
        provider_kind="fake",
        model="fake-model",
        updated_at=datetime(2026, 1, day, tzinfo=UTC),
        **extra,
    )
    db.add(m)
    db.commit()
    return m


def _rule(db, text, kind="cover_letter", origin="learned", status="active", sources=(), day=1):
    r = StyleRule(
        id=uuid.uuid4(),
        kind=kind,
        text=text,
        origin=origin,
        status=status,
        source_material_ids=list(sources),
        created_at=datetime(2026, 1, day, tzinfo=UTC),
    )
    db.add(r)
    db.commit()
    return r


def test_style_tables_store_rules_and_material_columns(db_session):
    m = _edited(db_session)
    r = _rule(db_session, "Open with a result.", sources=[m.id])
    m.style_rules, m.style_learned_at = ["Open with a result."], datetime.now(UTC)
    db_session.commit()
    assert db_session.get(StyleRule, r.id).source_material_ids == [m.id]
    assert db_session.get(Material, m.id).style_rules == ["Open with a result."]
    for bad in ({"kind": "outreach"}, {"origin": "guess"}, {"status": "gone"}):
        with pytest.raises(IntegrityError):
            _rule(db_session, "x", **bad)
        db_session.rollback()


def test_check_rules_filters_model_output():
    rules = [
        LearnedRule(text="  ", samples=[1]),
        LearnedRule(text="x" * 201, samples=[1]),
        LearnedRule(text="No valid sample.", samples=[7, 0]),
        LearnedRule(text="never use  BULLET points.", samples=[1]),  # 和 blocked 相同
        LearnedRule(text="Drop the [NEEDS CONFIRMATION] placeholders.", samples=[1]),  # 占位符不能当规则
        LearnedRule(text=" Rule 0. ", samples=[1, 9]),
        LearnedRule(text="rule 0.", samples=[2]),  # 和上一条相同
        *[LearnedRule(text=f"Rule {i}.", samples=[2]) for i in range(1, 10)],
    ]
    kept = check_rules(rules, n_samples=2, blocked=["Never use bullet points."])
    assert [r.text for r in kept] == [f"Rule {i}." for i in range(8)]
    assert kept[0].samples == [1]  # 无效编号 9 被去掉
    one_line = check_rules([LearnedRule(text="Line one.\nLine two.", samples=[1])], n_samples=1, blocked=[])
    assert [r.text for r in one_line] == ["Line one. Line two."]


def test_learn_adds_rules_and_marks_samples(client, monkeypatch):
    monkeypatch.setitem(
        STYLE_REPLY,
        "rules",
        [
            {"text": "Open with the most relevant result.", "samples": [1, 2]},
            {"text": "Keep it under 150 words.", "samples": [2]},
        ],
    )
    with get_sessionmaker()() as db:
        new = _edited(db, day=2, draft="Draft B.", final="Final B.")
        old = _edited(db, day=1, draft="Draft A.", final="Final A.")
        _edited(db, day=3, draft="Unedited draft.", final=None)
        _edited(db, day=3, kind="qa", question="Why us?", draft="QA draft.", final="QA final.")
        _rule(db, "Use bullet points.", status="removed")
        _rule(db, "No emojis.", origin="manual")
        result = learn_style(db, "cover_letter")
        db.commit()
        assert result.added == ["Open with the most relevant result.", "Keep it under 150 words."]
        assert result.dropped == []
        learned = {
            r.text: r
            for r in db.scalars(select(StyleRule).where(StyleRule.origin == "learned", StyleRule.status == "active"))
        }
        assert set(learned["Open with the most relevant result."].source_material_ids) == {new.id, old.id}
        assert learned["Keep it under 150 words."].source_material_ids == [old.id]  # 样本 2 是较旧的那份
        assert db.get(Material, new.id).style_learned_at and db.get(Material, old.id).style_learned_at
        prompt = client.fake.calls[-1][0][-1].content
        assert prompt.index("Draft B.") < prompt.index("Draft A.") and "Final A." in prompt
        assert "Unedited draft." not in prompt and "QA draft." not in prompt
        assert "Use bullet points." in prompt and "No emojis." in prompt  # 模型看得到删掉的和自己加的


def test_learn_qa_prompt_includes_the_question(client, monkeypatch):
    with get_sessionmaker()() as db:
        _edited(db, kind="qa", question="Why are you a good fit?", draft="QA draft.", final="QA final.")
        learn_style(db, "qa")
        assert "Why are you a good fit?" in client.fake.calls[-1][0][-1].content


def test_relearn_keeps_ids_reports_changes_and_never_brings_back_removed(client, monkeypatch):
    with get_sessionmaker()() as db:
        a = _edited(db, day=1)
        keep = _rule(db, "Open with a result.", sources=[a.id, uuid.uuid4()])  # 第二个来源已经不存在
        gone = _rule(db, "Use three paragraphs.", sources=[a.id])
        manual = _rule(db, "No emojis.", origin="manual")
        removed = _rule(db, "Use bullet points.", status="removed")
        b = _edited(db, day=2)
        monkeypatch.setitem(
            STYLE_REPLY,
            "rules",
            [
                {"text": "open with a  result.", "samples": [1]},  # 同一条，样本 1 = b
                {"text": "USE BULLET POINTS.", "samples": [1]},  # 用户删过的
                {"text": "Use bullet points", "samples": [1]},  # 少了句号也是同一条
                {"text": "Keep it under 150 words.", "samples": [1, 2]},
            ],
        )
        result = learn_style(db, "cover_letter")
        db.commit()
        assert result.added == ["Keep it under 150 words."] and result.dropped == ["Use three paragraphs."]
        kept = db.get(StyleRule, keep.id)
        assert kept.text == "Open with a result." and set(kept.source_material_ids) == {a.id, b.id}
        assert db.get(StyleRule, gone.id) is None
        assert db.get(StyleRule, manual.id).status == "active" and db.get(StyleRule, removed.id).status == "removed"
        assert db.scalar(select(StyleRule).where(StyleRule.text == "USE BULLET POINTS.")) is None
        assert db.scalar(select(StyleRule).where(StyleRule.text == "Use bullet points")) is None


def test_learn_keeps_rules_when_nothing_valid_comes_back(client, monkeypatch):
    with get_sessionmaker()() as db:
        a = _edited(db)
        keep = _rule(db, "Open with a result.", sources=[a.id])
        monkeypatch.setitem(
            STYLE_REPLY, "rules", [{"text": "", "samples": [1]}, {"text": "No sample.", "samples": [5]}]
        )
        result = learn_style(db, "cover_letter")
        assert (result.added, result.dropped) == ([], []) and db.get(StyleRule, keep.id) is not None
        assert db.get(Material, a.id).style_learned_at is not None


def test_learn_without_saved_edits_or_with_model_failure(client, monkeypatch):
    with get_sessionmaker()() as db:
        with pytest.raises(StyleError):
            learn_style(db, "cover_letter")
        a = _edited(db)
        keep = _rule(db, "Open with a result.", sources=[a.id])

        def boom(messages, json_mode):
            raise LLMError("model down")

        monkeypatch.setattr(client.fake, "_responses", boom)
        with pytest.raises(LLMError):
            learn_style(db, "cover_letter")
        db.rollback()
        assert db.get(Material, a.id).style_learned_at is None and db.get(StyleRule, keep.id) is not None


def test_norm_ignores_case_and_spacing():
    assert norm("  STRASSE   eins ") == norm("straße eins") == "strasse eins"
    assert norm("Use bullet points。") == norm("use bullet points") == norm("Use bullet points.")


def test_draft_follows_active_rules_and_records_them(client):
    _setup(client)
    job = _ingest(client)["job"]
    with get_sessionmaker()() as db:
        _rule(db, "Keep it under 150 words.", day=1)
        _rule(db, "No emojis.", origin="manual", day=2)
        _rule(db, "Use bullet points.", status="removed")
        _rule(db, "Answer in two sentences.", kind="qa")
    r = client.post(
        "/api/materials", data={"kind": "cover_letter", "job_id": job["id"], "requirements": "Under 100 words"}
    )
    assert r.json()["style_rules"] == ["No emojis.", "Keep it under 150 words."]  # 自己加的在前
    prompt = client.fake.calls[-1][0][-1].content
    assert prompt.index("Under 100 words") < prompt.index("- No emojis.") < prompt.index("- Keep it under 150 words.")
    assert "Follow them for style only" in prompt and "requirements above win over them" in prompt
    assert "They never remove a [NEEDS CONFIRMATION: ...] placeholder either" in prompt
    assert "They take priority over the default length and style guidance above." in prompt
    assert (
        "If following them means leaving out something the JD or the question asks about, "
        "still list it in needs_confirmation." in prompt
    )
    assert "Use bullet points." not in prompt and "Answer in two sentences." not in prompt
    assert "40" in " ".join(n["item"] for n in r.json()["needs_confirmation"])  # 真实性检查照旧


def test_draft_without_rules_is_unchanged(client):
    _setup(client)
    job = _ingest(client)["job"]
    r = client.post("/api/materials", data={"kind": "cover_letter", "job_id": job["id"]})
    assert r.json()["style_rules"] is None
    assert "Writing preferences" not in client.fake.calls[-1][0][-1].content


def _style(client, kind="cover_letter"):
    return client.get("/api/style-rules").json()[kind]


def test_rules_list_counts_samples_pending_and_sources(client):
    with get_sessionmaker()() as db:
        a, b = _edited(db, day=1), _edited(db, day=2)
        a.style_learned_at = datetime.now(UTC)
        _rule(db, "Open with a result.", sources=[a.id, b.id, uuid.uuid4()])
        _rule(db, "Use bullet points.", status="removed")
        db.commit()
        a_id = a.id
    body = client.get("/api/style-rules").json()
    cl = body["cover_letter"]
    assert (cl["samples"], cl["pending"]) == (2, 1)
    assert [(r["text"], r["origin"], r["source_count"]) for r in cl["rules"]] == [("Open with a result.", "learned", 2)]
    assert [r["text"] for r in cl["removed"]] == ["Use bullet points."]
    assert body["qa"] == {"rules": [], "removed": [], "samples": 0, "pending": 0}
    assert client.delete(f"/api/materials/{a_id}").status_code == 204  # 删掉一份草稿
    assert _style(client)["rules"][0]["source_count"] == 1 and _style(client)["samples"] == 1


def test_add_remove_restore_rule(client):
    r = client.post("/api/style-rules", json={"kind": "qa", "text": "  Answer in two sentences.  "})
    assert r.status_code == 201 and r.json()["text"] == "Answer in two sentences." and r.json()["origin"] == "manual"
    rid = r.json()["id"]
    for bad in (
        "answer in  two sentences.",
        " ",
        "x" * 201,
        "Never use [NEEDS CONFIRMATION] placeholders.",
        "不要写需要确认",
    ):
        assert client.post("/api/style-rules", json={"kind": "qa", "text": bad}).status_code == 422
    assert client.patch(f"/api/style-rules/{rid}", json={"status": "removed"}).json()["status"] == "removed"
    assert _style(client, "qa")["rules"] == [] and len(_style(client, "qa")["removed"]) == 1
    back = client.post("/api/style-rules", json={"kind": "qa", "text": "Answer in two sentences."})
    assert back.json()["id"] == rid and back.json()["status"] == "active"  # 和删掉的相同 → 恢复那一条
    assert client.patch(f"/api/style-rules/{uuid.uuid4()}", json={"status": "removed"}).status_code == 404
    two = client.post("/api/style-rules", json={"kind": "qa", "text": "Line one.\nLine two."})
    assert two.status_code == 201 and two.json()["text"] == "Line one. Line two."  # 一条规则只占一行


def test_active_rules_are_capped_at_20(client):
    ids = [client.post("/api/style-rules", json={"kind": "qa", "text": f"Rule {i}."}).json()["id"] for i in range(20)]
    assert client.post("/api/style-rules", json={"kind": "qa", "text": "Rule 20."}).status_code == 422
    assert client.post("/api/style-rules", json={"kind": "cover_letter", "text": "Rule 20."}).status_code == 201
    client.patch(f"/api/style-rules/{ids[0]}", json={"status": "removed"})
    assert client.post("/api/style-rules", json={"kind": "qa", "text": "Rule 20."}).status_code == 201
    assert client.patch(f"/api/style-rules/{ids[0]}", json={"status": "active"}).status_code == 422  # 恢复也受上限限制


def test_learn_endpoint(client, monkeypatch):
    assert client.post("/api/style-rules/learn", json={"kind": "cover_letter"}).status_code == 422
    with get_sessionmaker()() as db:
        _edited(db)
    monkeypatch.setitem(STYLE_REPLY, "rules", [{"text": "Open with a result.", "samples": [1]}])
    r = client.post("/api/style-rules/learn", json={"kind": "cover_letter"})
    assert r.status_code == 200 and r.json()["added"] == ["Open with a result."] and r.json()["dropped"] == []
    assert r.json()["style"]["pending"] == 0 and r.json()["style"]["rules"][0]["source_count"] == 1

    def boom(messages, json_mode):
        raise LLMError("model down")

    monkeypatch.setattr(client.fake, "_responses", boom)
    assert client.post("/api/style-rules/learn", json={"kind": "cover_letter"}).status_code == 502
    assert [r["text"] for r in _style(client)["rules"]] == ["Open with a result."]  # 失败时规则不变


def test_saving_a_new_edit_makes_it_pending_again(client):
    with get_sessionmaker()() as db:
        m = _edited(db, draft="Draft.", final="Final.")
        m.style_learned_at = datetime.now(UTC)
        db.commit()
        mid = m.id
    client.patch(f"/api/materials/{mid}", json={"edited_text": "Final."})  # 内容没变
    assert _style(client)["pending"] == 0
    client.patch(f"/api/materials/{mid}", json={"edited_text": "Another version."})
    assert (_style(client)["samples"], _style(client)["pending"]) == (1, 1)
    client.patch(f"/api/materials/{mid}", json={"edited_text": "Draft."})  # 还原成原稿：不再是样本
    assert (_style(client)["samples"], _style(client)["pending"]) == (0, 0)


def test_material_out_names_the_job(client):
    _setup(client)
    job = _ingest(client)["job"]
    m = client.post("/api/materials", data={"kind": "cover_letter", "job_id": job["id"]}).json()
    assert (m["job_title"], m["company"]) == ("Senior Backend Engineer", "Example Robotics, Inc.")
    no_job = client.post("/api/materials", data={"kind": "qa", "question": "Why us?"}).json()
    assert no_job["job_title"] is None and no_job["company"] is None
    listed = {x["id"]: x for x in client.get("/api/materials").json()}
    assert listed[m["id"]]["company"] == "Example Robotics, Inc." and listed[no_job["id"]]["job_title"] is None


def test_strip_placeholders():
    out = strip_placeholders("I can start [NEEDS CONFIRMATION: start date].\n\n[需要确认：姓名]\n\nThanks.")
    assert "NEEDS CONFIRMATION" not in out and "需要确认" not in out
    assert "  " not in out and "\n\n\n" not in out
    assert "I can start" in out and "Thanks." in out


def test_learn_prompt_has_no_placeholders(client):
    with get_sessionmaker()() as db:
        _edited(db, draft="Dear team, I built APIs. [NEEDS CONFIRMATION: start date]", final="I built APIs.")
        learn_style(db, "cover_letter")
        prompt = client.fake.calls[-1][0][-1].content
        assert "I built APIs." in prompt and "NEEDS CONFIRMATION: start date" not in prompt


def test_learn_prompt_cuts_long_samples(client):
    with get_sessionmaker()() as db:
        _edited(db, draft="x" * 7000, final="Short.")
        learn_style(db, "cover_letter")
        prompt = client.fake.calls[-1][0][-1].content
        assert "x" * 6000 in prompt and "x" * 6001 not in prompt


def test_learn_twice_still_reads_the_latest_eight(client):
    with get_sessionmaker()() as db:
        edits = [_edited(db, day=d, draft=f"Draft {d:02d}.", final=f"Final {d:02d}.") for d in range(1, 13)]
        first_id, untouched_id = edits[0].id, edits[11].id
        learn_style(db, "cover_letter")
        db.commit()
        assert db.get(Material, untouched_id).updated_at == datetime(2026, 1, 12, tzinfo=UTC)  # 整理不改 updated_at
    client.patch(f"/api/materials/{first_id}", json={"edited_text": "A newer final."})  # 第 1 份变成最新
    with get_sessionmaker()() as db:
        learn_style(db, "cover_letter")
        db.commit()
    prompt = client.fake.calls[-1][0][-1].content
    assert all(f"Draft {d:02d}." in prompt for d in (1, *range(6, 13)))
    assert not any(f"Draft {d:02d}." in prompt for d in range(2, 6))


def test_edit_saved_during_learning_stays_pending(client, monkeypatch):
    with get_sessionmaker()() as db:
        old = _edited(db, day=1)
        late: list[uuid.UUID] = []

        def respond(messages, json_mode):
            with get_sessionmaker()() as other:  # 模型执行时用户又保存了一份修改
                late.append(_edited(other, day=2).id)
            return json.dumps({"rules": [{"text": "Open with a result.", "samples": [1]}]})

        monkeypatch.setattr(client.fake, "_responses", respond)
        learn_style(db, "cover_letter")
        db.commit()
        assert db.get(Material, old.id).style_learned_at is not None
        assert db.get(Material, late[0]).style_learned_at is None


def test_rule_order_is_stable_across_learns(client, monkeypatch):
    texts = ["Zeta rule.", "Alpha rule.", "Mid rule.", "Beta rule.", "Omega rule.", "Gamma rule."]
    monkeypatch.setitem(STYLE_REPLY, "rules", [{"text": t, "samples": [1]} for t in texts])
    with get_sessionmaker()() as db:
        _edited(db)
        learn_style(db, "cover_letter")
        db.commit()
    assert [r["text"] for r in _style(client)["rules"]] == texts  # 照模型给的顺序
    # 第二次回传同样 6 条（顺序倒过来、来源多一份），列表顺序不变
    monkeypatch.setitem(STYLE_REPLY, "rules", [{"text": t, "samples": [1]} for t in reversed(texts)])
    with get_sessionmaker()() as db:
        _edited(db, day=2)
        result = learn_style(db, "cover_letter")
        db.commit()
        assert (result.added, result.dropped) == ([], [])
        assert active_rule_texts(db, "cover_letter") == texts
    assert [r["text"] for r in _style(client)["rules"]] == texts


def _learned_texts(db, kind="cover_letter"):
    rows = db.scalars(select(StyleRule).where(StyleRule.kind == kind, StyleRule.origin == "learned"))
    return sorted(r.text for r in rows if r.status == "active")


def test_rule_removed_during_learning_is_not_deleted_or_relearned(client, monkeypatch):
    with get_sessionmaker()() as db:
        m = _edited(db)
        a = _rule(db, "Open with a result.", sources=[m.id])
        b = _rule(db, "Use three paragraphs.", sources=[m.id])
        a_id, b_id = a.id, b.id

        def respond(messages, json_mode):
            with get_sessionmaker()() as other:  # 模型执行时用户删掉了 A
                other.get(StyleRule, a_id).status = "removed"
                other.commit()
            rules = [{"text": "open with a  RESULT.", "samples": [1]}, {"text": "Keep it short.", "samples": [1]}]
            return json.dumps({"rules": rules})

        monkeypatch.setattr(client.fake, "_responses", respond)
        result = learn_style(db, "cover_letter")
        db.commit()
        assert db.get(StyleRule, a_id).status == "removed"
        assert db.get(StyleRule, b_id) is None
        assert _learned_texts(db) == ["Keep it short."]
        assert (result.added, result.dropped) == (["Keep it short."], ["Use three paragraphs."])


def test_overlapping_learns_do_not_stack(client, monkeypatch):
    with get_sessionmaker()() as db:
        m = _edited(db)
        _rule(db, "Open with a result.", sources=[m.id])
        _rule(db, "Use three paragraphs.", sources=[m.id])

        def respond(messages, json_mode):
            with get_sessionmaker()() as other:  # 另一次整理同时写进了 D、E
                _rule(other, "Rule D.", day=2)
                _rule(other, "Rule E.", day=2)
            rules = [{"text": "Open with a result.", "samples": [1]}, {"text": "Keep it short.", "samples": [1]}]
            return json.dumps({"rules": rules})

        monkeypatch.setattr(client.fake, "_responses", respond)
        learn_style(db, "cover_letter")
        db.commit()
        assert _learned_texts(db) == ["Keep it short.", "Open with a result."]
