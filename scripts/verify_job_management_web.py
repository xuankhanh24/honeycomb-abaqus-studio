"""Local UI acceptance with fixture API responses; never dispatches a real solver."""
import json
from pathlib import Path
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from honeycomb_studio.cloud_api import create_app
from honeycomb_studio.cloud_matrix import matrix_entries, prepare, workflow_title
from honeycomb_studio.models import BatchSpec, ModelSpec, digest

root = Path(__file__).resolve().parents[1]

spec = BatchSpec(model=ModelSpec(core_topology="reentrant_0", reentrant_geometry="angle", cpus=4, duration=.012),
                 axes=[{"parameter": "reentrant_delta_deg", "values": [25, 26, 27]}]).model_dump()
job = prepare({"id": "a" * 32, "name": "Kiểm thử giao diện", "status": "draft", "spec": spec,
               "profile": "research", "input_hash": digest(spec)}, 123)
labels = {e["child_id"]: e["display_name"] for e in matrix_entries(job)["include"]}
for i, shard in enumerate(job["shards"]):
    shard.update(status="failed" if i == 1 else "completed", archive_verified=i != 1,
                 display_name=labels[shard["id"]], workflow_run_id=123, runs=[])
job.update(status="failed", workflow={"status": "completed", "conclusion": "failure"}, parameter_title=workflow_title(spec))
with TestClient(create_app()) as client:
    template = client.get("/api/template").json()
(root / "output").mkdir(exist_ok=True)
requests = []

def handle(route):
    path = urlparse(route.request.url).path
    if path == '/api/template':
        value = template
    elif path == '/api/status':
        value = {'gates': [], 'max_runs': 100, 'execution_runtime': {}}
    elif path == '/api/session':
        value = {'owner': True, 'csrf': 'local-fixture'}
    elif path == '/api/jobs':
        value = {'jobs': [{k: job[k] for k in ('id', 'name', 'profile', 'status', 'workflow_run_id', 'parameter_title')}]}
    elif path == '/api/activity':
        value = {'available': True, 'runs': []}
    elif path == '/api/training':
        value = {'collection': None}
    elif path.endswith('/recover'):
        requests.append(path)
        job['recovery_dispatch_pending'] = True
        value = {'recovery_dispatch_pending': True}
    elif path == '/api/jobs/' + job['id']:
        value = job
    elif path == '/api/geometry':
        value = {'plane': 'xz', 'width': 100, 'height': 100, 'depth': 20, 'walls': []}
    else:
        value = {}
    route.fulfill(status=200, content_type='application/json', body=json.dumps(value))

with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    for width, height, label in [(1440, 1000, 'desktop'), (390, 844, 'mobile')]:
        page = browser.new_page(viewport={'width': width, 'height': height})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/api/**', handle)
        page.goto('http://127.0.0.1:8768', wait_until='networkidle')
        page.get_by_role('button', name='Công việc', exact=True).click()
        page.get_by_role('button', name='Mở bài', exact=True).click()
        panel = page.get_by_role('region', name='Tiến trình và thao tác job')
        expect(panel.get_by_text('Lượt 2/3', exact=False)).to_be_visible()
        panel.get_by_role('button', name='Chạy bù 1 lượt lỗi', exact=False).click()
        expect(panel.get_by_role('heading', name='Chạy bù 1 lượt cần xử lý')).to_be_visible()
        panel.scroll_into_view_if_needed()
        page.screenshot(path=str(root / f'output/admin-management-{label}.png'), full_page=True)
        if label == 'desktop':
            panel.get_by_role('button', name='Xác nhận chạy bù', exact=True).click()
            expect(panel.get_by_text('Đã gửi yêu cầu chạy bù. Đợi GitHub nhận bài.')).to_be_visible()
            assert len(requests) == 1
            job.pop('recovery_dispatch_pending', None)
        else:
            panel.get_by_role('button', name='Quay lại', exact=True).click()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Horizontal overflow'
        assert not errors, errors
        print(label, 'PASS: parameter titles, per-run disclosure, recovery scope, no page errors/overflow')
        page.close()
    browser.close()

