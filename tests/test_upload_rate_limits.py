import hashlib

import httpx
import pytest

from honeycomb_studio.cloud_archive import ReleaseArchive
from honeycomb_studio.cloud_github import Github


@pytest.mark.parametrize('mode', ['retry_after', 'secondary', 'primary'])
def test_upload_recovers_rate_limited_403_without_losing_payload(tmp_path, monkeypatch, mode):
    payload = b'complete solver output'
    path = tmp_path / 'result.odb'
    path.write_bytes(payload)
    waits = []
    monkeypatch.setattr('time.sleep', waits.append)
    monkeypatch.setattr('time.time', lambda: 1000)
    posts = []
    asset = {'id': 7, 'name': 'result.part', 'size': len(payload),
             'digest': 'sha256:' + hashlib.sha256(payload).hexdigest(),
             'browser_download_url': 'https://github.com/fixture/result.part'}

    def handler(request):
        if request.method == 'GET':
            return httpx.Response(200, json=[])
        posts.append(request.read())
        if len(posts) == 1:
            headers = {'retry-after': '75'} if mode == 'retry_after' else (
                {'x-ratelimit-remaining': '0', 'x-ratelimit-reset': '1120'} if mode == 'primary' else {})
            return httpx.Response(403, headers=headers, json={'message': 'You have exceeded a secondary rate limit.'})
        return httpx.Response(201, json=asset)

    github = Github(token='fixture', client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert ReleaseArchive(github, 1).upload(path, 'result.part')['asset_id'] == 7
    assert posts == [payload, payload]
    assert len(waits) == 1
    assert waits[0] >= {'retry_after': 75, 'secondary': 60, 'primary': 120}[mode]


def test_permanent_upload_403_is_not_retried(tmp_path, monkeypatch):
    path = tmp_path / 'result'
    path.write_bytes(b'fixture')
    waits = []
    monkeypatch.setattr('time.sleep', waits.append)

    def handler(request):
        return httpx.Response(200, json=[]) if request.method == 'GET' else httpx.Response(
            403, json={'message': 'Resource not accessible by integration'})

    github = Github(token='fixture', client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(httpx.HTTPStatusError):
        ReleaseArchive(github, 1).upload(path, 'result.part')
    assert waits == []


def test_catalog_get_respects_rate_limit_reset(monkeypatch):
    waits = []
    monkeypatch.setattr('time.sleep', waits.append)
    calls = []

    def handler(request):
        calls.append(request)
        return (httpx.Response(403, headers={'retry-after': '61'}, json={'message': 'API rate limit exceeded'})
                if len(calls) == 1 else httpx.Response(200, json={'ok': True}))

    github = Github(token='fixture', client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert github.repo('GET', '/fixture') == {'ok': True}
    assert len(waits) == 1 and waits[0] >= 61


def test_many_uploads_inventory_release_once(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == 'GET':
            return httpx.Response(200, json=[])
        payload = request.read()
        return httpx.Response(201, json={'id': len(calls), 'name': request.url.params['name'],
            'size': len(payload), 'digest': 'sha256:' + hashlib.sha256(payload).hexdigest(),
            'browser_download_url': 'https://github.com/fixture/asset'})

    archive = ReleaseArchive(Github(token='fixture', client=httpx.Client(transport=httpx.MockTransport(handler))), 1)
    for i in range(10):
        path = tmp_path / str(i)
        path.write_bytes(str(i).encode())
        archive.upload(path, path.name)
    assert calls.count('GET') == 1
    assert calls.count('POST') == 10
