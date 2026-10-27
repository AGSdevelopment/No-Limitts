# Iteration 13: forms audiences (Everyone for 6 Week / 3-6-12 Month), Task Creation form (Support Office), new starter groups, task attachments
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL").rstrip("/")
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}


def _forms(h):
    r = requests.get(f"{BASE_URL}/api/forms", headers=h)
    assert r.status_code == 200
    return r.json()


# Forms audiences
def test_employee_sees_review_forms_not_task_creation():
    titles = [f["title"] for f in _forms(EMP)]
    assert any("6 Week" in t for t in titles), titles
    assert any("3/6/12" in t for t in titles), titles
    assert not any("Task Creation" in t for t in titles), titles


def test_admin_task_creation_form_support_office():
    f = [x for x in _forms(ADMIN) if "Task Creation" in x["title"]]
    assert len(f) == 1
    assert f[0]["category"] == "Support Office"
    assert f[0]["audiences"] == ["support_office"]


def test_review_forms_everyone():
    for f in _forms(ADMIN):
        if "6 Week" in f["title"] or "3/6/12" in f["title"]:
            assert f.get("audiences") in ([], None), f


# New starter groups on test employee (reverted)
def test_set_new_starter_groups_and_revert():
    me = requests.get(f"{BASE_URL}/api/auth/me", headers=EMP).json()
    orig = me.get("staff_group")
    try:
        for g in ["new_starter_employee", "new_starter_contractor"]:
            r = requests.patch(f"{BASE_URL}/api/users/user_testemp001/group", headers=ADMIN, json={"staff_group": g})
            assert r.status_code == 200, r.text
            assert requests.get(f"{BASE_URL}/api/auth/me", headers=EMP).json().get("staff_group") == g
        r = requests.patch(f"{BASE_URL}/api/users/user_testemp001/group", headers=ADMIN, json={"staff_group": "bogus"})
        assert r.status_code in (400, 422)
    finally:
        requests.patch(f"{BASE_URL}/api/users/user_testemp001/group", headers=ADMIN, json={"staff_group": orig})


# Task attachments
def test_task_attachment_flow():
    up = requests.post(f"{BASE_URL}/api/tasks/attachments", headers=ADMIN,
                       files={"file": ("TEST_attach.txt", b"hello attachment", "text/plain")})
    assert up.status_code == 200, up.text
    fid = up.json()["file_id"]
    # employee can't attach admin's file
    r = requests.post(f"{BASE_URL}/api/tasks", headers=EMP, json={"title": "TEST_emp_bad", "attachment_id": fid})
    assert r.status_code == 404
    # admin assigns to employee with attachment
    r = requests.post(f"{BASE_URL}/api/tasks", headers=ADMIN,
                      json={"title": "TEST_attach_task", "assignee_id": "user_testemp001", "attachment_id": fid})
    assert r.status_code == 200, r.text
    tasks = requests.get(f"{BASE_URL}/api/tasks?scope=mine", headers=EMP).json()
    t = [x for x in tasks if x["title"] == "TEST_attach_task"]
    assert t and t[0]["attachment"]["file_id"] == fid
    try:
        g = requests.get(f"{BASE_URL}/api/tasks/files/{fid}?token=test_session_employee")
        assert g.status_code == 200 and g.content == b"hello attachment"
        assert requests.get(f"{BASE_URL}/api/tasks/files/{fid}").status_code == 401
    finally:
        for x in t:
            requests.delete(f"{BASE_URL}/api/tasks/{x['task_id']}", headers=ADMIN)
