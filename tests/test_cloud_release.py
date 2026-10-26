import pytest

from honeycomb_studio.cloud_release import reserve_release


class Fake:
    def __init__(self, *, existing=False, moved=False, wrong_tag=False):
        self.existing, self.moved, self.wrong_tag = existing, moved, wrong_tag
        self.calls = []

    def repo(self, method, path, body=None, **kwargs):
        self.calls.append((method, path, body))
        ref = {"object": {"type": "commit", "sha": "wrong" if self.wrong_tag else "source"}}
        if path.startswith("/git/ref/tags/"):
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
