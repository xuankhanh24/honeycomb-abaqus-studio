# -*- coding: utf-8 -*-
"""Abaqus Python 2.7: native histories, every rear frame and impactor contact sums."""
from __future__ import print_function

import json
import os

import numpy as np
from odbAccess import openOdb

from rear_metrics_bulk import RearMetrics


def dump(path, value):
    temporary = path + '.tmp'
    with open(temporary, 'w') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
    if os.path.exists(path):
        os.remove(path)
    os.rename(temporary, path)


def contact_statistics(field, impactor):
    subset = field.getSubset(region=impactor)
    try:
        blocks = [np.asarray(block.data, dtype=np.float64) for block in subset.bulkDataBlocks]
    except Exception:
        from damage_metrics import value_data
        blocks = [np.asarray([value_data(value) for value in subset.values], dtype=np.float64)]
    count = 0
    sums = np.zeros(3)
    minimum = np.ones(3) * np.inf
    maximum = np.ones(3) * -np.inf
    for data in blocks:
        if not data.size:
            continue
        if data.ndim != 2 or data.shape[1] != 3 or not np.isfinite(data).all():
            raise ValueError('Invalid native contact vectors')
        count += len(data)
        sums += data.sum(axis=0)
        minimum = np.minimum(minimum, data.min(axis=0))
        maximum = np.maximum(maximum, data.max(axis=0))
    return {'rows': count, 'finite_count': [count] * 3, 'sum': sums.tolist(),
            'min': minimum.tolist() if count else [None] * 3,
            'max': maximum.tolist() if count else [None] * 3}


def run(config):
    if config.get('full_fields', True) or not config.get('damage_metrics'):
        raise ValueError('Validation metrics require reduced output and native damage fields')
    if config.get('frame_indices') is not None:
        raise ValueError('Validation must inspect every native rear/contact frame')
    out = config['extract_directory']
    for directory in (out, os.path.join(out, 'spool'), os.path.join(out, 'reduced-fields')):
        if not os.path.isdir(directory):
            os.makedirs(directory)
    odb = openOdb(path=str(config['odb']), readOnly=True)
    try:
        rear = RearMetrics(odb)
        impactor = next(v for k, v in odb.rootAssembly.instances.items() if k.upper() == 'IMPACTOR-1')
        histories = []
        inventory = {'schema_version': '1', 'export_profile': 'validation_metrics',
                     'odb_version': str(odb.jobData.version), 'steps': [], 'fields': [], 'frames': 0,
                     'scope': 'All native histories, all rear frames and impactor contact-vector sums; no full S/U/PEEQ matrix duplication'}
        sequence = 0
        for step_name, step in odb.steps.items():
            inventory['steps'].append({'name': step_name, 'time_period': step.timePeriod,
                                       'total_time': step.totalTime, 'frames': len(step.frames)})
            for region_name, region in step.historyRegions.items():
                for variable, series in region.historyOutputs.items():
                    histories.append({'step': step_name, 'region': region_name, 'variable': variable,
                                      'description': series.description, 'data': list(series.data)})
            dump(os.path.join(out, 'histories.json'), histories)
            for index, frame in enumerate(step.frames):
                total_time = step.totalTime + frame.frameValue
                rear.frame(frame, total_time)
                for name, field in frame.fieldOutputs.items():
                    if not name.startswith(('CNORMF', 'CSHEARF')):
                        continue
                    statistics = contact_statistics(field, impactor)
                    record = {'step': step_name, 'frame': index, 'time_s': total_time,
                              'field': name, 'components': list(field.componentLabels),
                              'rows': statistics['rows'], 'statistics': statistics,
                              'reduction': 'contact_vectors_on_impactor_only',
                              'impactor_force_z_N': statistics['sum'][2]}
                    dump(os.path.join(out, 'reduced-fields', 'part-%08d.json' % sequence), record)
                    inventory['fields'].append(dict((k, record[k]) for k in ('step', 'frame', 'field', 'rows')))
                    sequence += 1
                inventory['frames'] += 1
                if index % 10 == 0 or index == len(step.frames) - 1:
                    dump(os.path.join(out, 'progress.json'), {'step': step_name, 'frame': index,
                         'frames_total': len(step.frames), 'time_s': frame.frameValue, 'chunks': sequence})
        dump(os.path.join(out, 'damage-summary.json'), rear.summary())
        dump(os.path.join(out, 'rear-field-history.json'), rear.rows)
        inventory['chunks'] = sequence
        dump(os.path.join(out, 'inventory.json'), inventory)
        dump(os.path.join(out, 'complete.json'), {'complete': True, 'chunks': sequence, 'profile': 'validation_metrics'})
    finally:
        odb.close()
