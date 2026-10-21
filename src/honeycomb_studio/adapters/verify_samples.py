# -*- coding: utf-8 -*-
"""Read-only acceptance: compare exported rows to independent ODB FieldValue access."""
import json, sys
import numpy as np
from odbAccess import openOdb

cfg = json.load(open(sys.argv[-1]))
odb = openOdb(path=str(cfg['odb']), readOnly=True)
results = []
try:
    for sample in cfg['samples']:
        field = odb.steps[str(sample['step'])].frames[sample['frame']].fieldOutputs[str(sample['field'])]
        matched = None
        for value in field.values:
            instance = getattr(getattr(value, 'instance', None), 'name', '')
            section = getattr(getattr(value, 'sectionPoint', None), 'number', -1)
            if instance != sample['instance'] or (sample['section_point'] >= 0 and section != sample['section_point']):
                continue
            if sample['node_label'] >= 0 and getattr(value, 'nodeLabel', -1) != sample['node_label']:
                continue
            if sample['element_label'] >= 0 and getattr(value, 'elementLabel', -1) != sample['element_label']:
                continue
            if sample['integration_point'] >= 0 and getattr(value, 'integrationPoint', -1) != sample['integration_point']:
                continue
            if str(value.position) != sample['position']:
                continue
            try:
                data = value.data
            except Exception:
                data = value.dataDouble
            matched = [float(data)] if np.isscalar(data) else [float(x) for x in data]
            break
        passed = matched is not None and np.allclose(matched, sample['data'], rtol=1e-6, atol=1e-8)
        components_match = list(field.componentLabels) == sample['components']
        results.append({'sample': sample, 'odb_data': matched, 'passed': bool(passed and components_match)})
finally:
    odb.close()
with open(cfg['result'], 'w') as f:
    json.dump({'passed': all(r['passed'] for r in results), 'samples': results}, f, indent=2)
if not all(r['passed'] for r in results):
    raise RuntimeError('ODB sample comparison failed')
