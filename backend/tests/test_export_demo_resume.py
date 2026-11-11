import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export_demo_resume.py"
spec = importlib.util.spec_from_file_location("export_demo_resume", SCRIPT)
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)

BASICS = {"name": "Alex Sample", "email": "alex@example.com", "phone": "555-010-0199", "location": "Remote", "links": []}


def test_public_resume_removes_contact_details():
    out = export.public_resume({"basics": BASICS, "summary": "Worked 2019 - 2023.", "skills": []})
    assert out["basics"]["email"] == ""
    assert out["basics"]["phone"] == ""
    assert out["basics"]["name"] == "Alex Sample"


@pytest.mark.parametrize("text", ["Reach me at alex@example.com", "Call (555) 010-0199"])
def test_public_resume_refuses_contact_details_in_body(text):
    with pytest.raises(ValueError):
        export.public_resume({"basics": BASICS, "summary": text, "skills": []})
