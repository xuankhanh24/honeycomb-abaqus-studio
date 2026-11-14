"""Plot matched retrospective OOF errors without treating training diagnostics as validation."""
import argparse
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from honeycomb_studio.surrogate_reliability import read_csv, regression_metrics, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--v5', type=Path, required=True)
    parser.add_argument('--v6', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rows = [read_csv(root / 'nested-oof-predictions.csv') for root in (args.v5, args.v6)]
    if [r['design_id'] for r in rows[0]] != [r['design_id'] for r in rows[1]]:
        raise ValueError('Paired comparison requires identical sample ordering')
    truth = np.array([float(r['actual_SEA_J_kg']) for r in rows[0]])
    if not np.allclose(truth, [float(r['actual_SEA_J_kg']) for r in rows[1]], rtol=1.e-12):
        raise ValueError('Source targets differ')
    predictions = [np.array([float(r['predicted_SEA_J_kg']) for r in rs]) for rs in rows]
    metrics = [regression_metrics(truth, pred) for pred in predictions]
    errors = [abs(pred - truth) for pred in predictions]
    deleted = np.array([r['rear_skin_deleted'] == 'True' for r in rows[0]])
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.spines.top': False,
                         'axes.spines.right': False})
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), constrained_layout=True)
    colors = ('#64748b', '#00796b')
    labels = ('v5: direct SEA selection', 'v6: exact-mass candidates added')
    axes[0].scatter(truth[~deleted], predictions[1][~deleted], s=18, alpha=.65, color=colors[1], label='Rear intact')
    axes[0].scatter(truth[deleted], predictions[1][deleted], s=18, alpha=.65, color='#c2410c', label='Rear deletion')
    endpoints = [min(truth.min(), predictions[1].min()), max(truth.max(), predictions[1].max())]
    axes[0].plot(endpoints, endpoints, '--', color='#334155', linewidth=1)
    axes[0].set(xlabel='FEA SEA at 8 ms (J/kg)', ylabel='Outer-heldout prediction (J/kg)',
                title=f'v6 OOF predictions, n={len(truth)}')
    axes[0].legend(frameon=False)
    for error, label, color, score in zip(errors, labels, colors, metrics, strict=True):
        axes[1].plot(np.sort(error), np.arange(1, len(error) + 1) / len(error), color=color,
                     label=f'{label}\nMAE {score["mae_J_kg"]:.2f} J/kg', linewidth=2)
    axes[1].set(xlabel='Absolute error (J/kg)', ylabel='Empirical cumulative fraction',
                title='Matched outer folds and source IDs', ylim=(0, 1))
    axes[1].legend(frameon=False, fontsize=8, loc='lower right')
    positions = np.arange(2)
    for i, (error, label, color) in enumerate(zip(errors, labels, colors, strict=True)):
        values = [error[~deleted].mean(), error[deleted].mean()]
        axes[2].bar(positions + (i - .5) * .34, values, width=.34, color=color, label=label.split(':')[0])
    axes[2].set_xticks(positions, [f'Rear intact\nn={(~deleted).sum()}', f'Rear deletion\nn={deleted.sum()}'])
    axes[2].set(ylabel='MAE (J/kg)', title='Errors remain unequal across regimes')
    axes[2].legend(frameon=False)
    fig.suptitle('Lưu Xuân Khánh — Retrospective surrogate audit, fixed 8-ms target\n'
                 'No physical-validation or optimized-point coverage claim', fontsize=13)
    fig.savefig(args.output / 'reliability-comparison.png', dpi=200)
    fig.savefig(args.output / 'reliability-comparison.svg')
    plt.close(fig)
    write_json(args.output / 'comparison.json', {
        'v5': metrics[0], 'v6': metrics[1], 'matched_outer_folds': True,
        'mae_reduction_percent': 100 * (1 - metrics[1]['mae_J_kg'] / metrics[0]['mae_J_kg']),
        'status': 'retrospective_comparison_requires_fresh_fea', 'physical_validation': 'not_established'})
    print(args.output)


if __name__ == '__main__':
    main()
