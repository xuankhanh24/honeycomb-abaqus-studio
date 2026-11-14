"""Budget native research retention without relaxing the independent reserve."""

import pytest

from honeycomb_studio.engine import Engine
from honeycomb_studio.execution import disk_requirement, execution_plan
from honeycomb_studio.models import BatchSpec, ModelSpec
from honeycomb_studio.store import Store


def test_research_archive_is_opt_in_and_full_export_keeps_its_original_budget():
    requested = ModelSpec(core_topology='reentrant_0', reentrant_geometry='angle', cpus=4,
                      duration=.012, field_intervals=1200, history_intervals=6000,
                      cell_size=8.139179762204378, reentrant_cell_height=5.173471740003828)
    model = requested.resolved()
    spec = BatchSpec(model=requested, min_free_gb=20).model_dump()
    ordinary = disk_requirement(spec, model)
    research = disk_requirement(spec, model, research_archive=True)
    assert research < ordinary
    capacity = spec['min_free_gb'] + (ordinary + research) / 2
    assert execution_plan(spec, [model], 4, 14, capacity)['effective_parallel_runs'] == 0
    plan = execution_plan(spec, [model], 4, 14, capacity, research_archive=True)
    assert plan['effective_parallel_runs'] == 1 and plan['disk_policy'] == 'research-hardlinks'
    assert spec['min_free_gb'] == 20
    assert execution_plan(spec, [model], 4, 14, research + 19.99,
                          research_archive=True)['effective_parallel_runs'] == 0
    assert execution_plan(spec, [model], 3, 14, capacity,
                          research_archive=True)['effective_parallel_runs'] == 0
    assert execution_plan(spec, [model], 4, 3, capacity,
                          research_archive=True)['effective_parallel_runs'] == 0
    spec['export_all_fields'] = True
    assert disk_requirement(spec, model, research_archive=True) == pytest.approx(ordinary)


@pytest.mark.parametrize('research', [False, True])
def test_both_native_engine_admission_gates_use_the_same_policy(tmp_path, monkeypatch, research):
    from types import SimpleNamespace

    request = BatchSpec(model=ModelSpec(cpus=4, duration=.012, field_intervals=1200))
    model = request.model.resolved()
    spec = request.model_dump()
    capacity = 20 + (disk_requirement(spec, model) + disk_requirement(spec, model, research_archive=True)) / 2
    monkeypatch.setattr('honeycomb_studio.engine.psutil.cpu_count', lambda: 4)
    monkeypatch.setattr('honeycomb_studio.engine.psutil.virtual_memory',
                        lambda: SimpleNamespace(available=14 * 1024**3))
    monkeypatch.setattr('honeycomb_studio.engine.shutil.disk_usage',
                        lambda _: SimpleNamespace(free=int(capacity * 1.e9)))
    store = Store(tmp_path)
    batch = store.create(request)
    engine = Engine(store, abaqus='fixture-not-invoked', fake=False)
    engine.research_archive = research

    def stop_before_native_command(*args):
        raise RuntimeError('fixture: admission passed; do not invoke a solver')

    monkeypatch.setattr(engine, '_monitor', stop_before_native_command)
    engine.execute_wave(store.list('runs', batch['id']), batch)
    assert bool(store.list('runs', batch['id'])[0]['attempts']) is research
    store.db.close()
