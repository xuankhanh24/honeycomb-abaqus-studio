import httpx
import pytest

from honeycomb_studio.cloud_github import Github
from honeycomb_studio.cloud_release import reserve_release


class Fake:
    def __init__(self, *, existing=False, moved=False, wrong_tag=False):
        self.existing, self.moved, self.wrong_tag = existing, moved, wrong_tag
        self.calls = []

    def repo(self, method, path, body=None, **kwargs):
        self.calls.append((method, path, body))
        ref = {"object": {"type": "commit", "sha": "wrong" if self.wrong_tag else "source"}}
        if path.startswith("/git/ref/tags/"):
            if path.endswith("/pinned-source"):
                return ref
            return ref if self.existing else None
        if path == "/git/refs":
            return ref
        if path == "/git/ref/heads/main":
            return {"object": {"sha": "new" if self.moved else "source"}}
        if path.startswith("/releases/tags/"):
            return None
        if path.startswith("/releases?"):
            return [{"id": 1, "draft": True, "tag_name": "test"}] if self.existing else []
        assert method == "POST"
        return {"id": 1, **body}


def test_reserve_before_main_moves_and_reuse_afterwards():
    github = Fake()
    assert reserve_release(github, tag="test", sha="source", name="Test")["draft"] is True
    assert next(path for method, path, _ in github.calls if method == "POST") == "/git/refs"
    github = Fake(existing=True, moved=True)
    assert reserve_release(github, tag="test", sha="source", name="Test")["id"] == 1
    assert not any(method == "POST" for method, _, _ in github.calls)


def test_refuse_unreserved_old_source_before_expensive_solver():
    github = Fake(moved=True)
    with pytest.raises(RuntimeError, match="no solver started"):
        reserve_release(github, tag="test", sha="source", name="Test")
    assert not any(method == "POST" for method, _, _ in github.calls)
    with pytest.raises(ValueError, match="exact workflow commit"):
        reserve_release(Fake(existing=True, wrong_tag=True), tag="test", sha="source", name="Test")


def test_late_collection_reservation_uses_already_pinned_workflow_source():
    github = Fake(moved=True)
    release = reserve_release(github, tag="test", sha="source", name="Test", source_tag="pinned-source")
    assert release["target_commitish"] == "source"
    assert ("POST", "/git/refs", {"ref": "refs/tags/test", "sha": "source"}) in github.calls


def test_late_collection_rejects_a_different_pinned_source():
    github = Fake(moved=True, wrong_tag=True)
    with pytest.raises(ValueError, match="exact workflow commit"):
        reserve_release(github, tag="test", sha="source", name="Test", source_tag="pinned-source")
    assert not any(method == "POST" for method, _, _ in github.calls)


@pytest.mark.parametrize("committed", [False, True])
def test_ref_creation_recovers_transient_422_without_retagging(monkeypatch, committed):
    monkeypatch.setattr("time.sleep", lambda _: None)
    state = {"exists": False, "posts": 0}

    def handler(request):
        path = request.url.path
        ref = {"object": {"type": "commit", "sha": "source"}}
        if path.endswith("/git/ref/tags/test"):
            return httpx.Response(200 if state["exists"] else 404, json=ref)
        if path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json=ref)
        if path.endswith("/git/refs"):
            state["posts"] += 1
            if state["posts"] == 1:
                state["exists"] = committed
                return httpx.Response(422, json={"message": "Reference creation failed"})
            state["exists"] = True
            return httpx.Response(201, json=ref)
        if "/releases/tags/" in path:
            return httpx.Response(404, json={})
        if path.endswith("/releases") and request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json={"id": 1})

    github = Github(token="fixture", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert reserve_release(github, tag="test", sha="source", name="Test")["id"] == 1
    assert state["posts"] == (1 if committed else 2)
