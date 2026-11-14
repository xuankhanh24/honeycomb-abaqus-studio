"""Preserve executed code, immutable inputs and checksums beside a completed study."""
import argparse
import json
import shutil
from pathlib import Path

from honeycomb_studio.surrogate_reliability import SOURCE_SHA256, sha256, write_json


def copy_verified(source, destination, expected=None):
    if destination.exists():
        if expected is not None and sha256(destination) != expected:
            raise ValueError('Existing snapshot differs: ' + str(destination))
        return
    if expected is not None and sha256(source) != expected:
        raise ValueError('Executed source changed before snapshot: ' + str(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--validation-dir', type=Path, required=True)
    args = parser.parse_args()
    study = args.study.resolve()
    if (study / 'delivery-checksums.json').exists():
        raise ValueError('Study delivery already sealed')
    checksums = json.loads((study / 'checksums.json').read_text(encoding='utf-8'))
    for name, expected in checksums.items():
        target = (study / name).resolve()
        target.relative_to(study)
        if sha256(target) != expected:
            raise ValueError('Completed study artifact changed: ' + name)
    protocol = json.loads((study / 'protocol.json').read_text(encoding='utf-8'))
    root = Path(__file__).resolve().parents[1]
    snapshot = study / 'executed-source'
    for name, expected in protocol['source_files'].items():
        source = Path(name).resolve()
        copy_verified(source, snapshot / source.relative_to(root), expected)
    # Transitive project imports are retained too. Preserve explicitly inventoried
    # executed bytes above even if the working checkout has since changed.
    for path in (root / 'src/honeycomb_studio').rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            copy_verified(path, snapshot / path.relative_to(root))
    for name in ('pyproject.toml', 'uv.lock'):
        copy_verified(root / name, snapshot / name)
    for name in ('package_reliability_study.py', 'verify_reliability_study.py'):
        copy_verified(root / 'scripts' / name, snapshot / 'scripts' / name)
    copy_verified(args.archive, study / 'data/source.zip', SOURCE_SHA256)
    for name in ('results-8ms-comparison.json', 'status-3bc66c62749746a7839df1a87392d798.json',
                 'locked-candidates.csv'):
        copy_verified(args.validation_dir / name, study / 'data/verification' / name,
                      sha256(args.validation_dir / name))
    flag = ' --physics-energy' if protocol.get('physics_energy') else ''
    text = f'''# Nghiên cứu {protocol['revision']} — Lưu Xuân Khánh

Đọc `BAO_CAO_DO_TIN_CAY.md` và `results.json` trước. Đây là nghiên cứu SEA lõi
tại **8 ms**, không phải SEA cuối sự kiện hoặc bằng chứng an toàn thực nghiệm.
Mọi điều kiện chưa đạt được giữ nguyên trong kết quả. Không có nghiệm tối ưu đã xác nhận.

- `protocol.json`: quy trình, nguồn, phiên bản thư viện, hash mã đã chạy.
- `split-ids.json`: các tập rời nhau; 78 test vẫn là test lịch sử đã được xem.
- `model-lock.json`, `research-models.joblib`: mô hình/threshold khóa trước đánh giá.
- `nested-oof-predictions.csv`: mỗi mẫu được dự báo ngoài fold huấn luyện tương ứng.
- `qualification-predictions.csv`: qualification nội bộ; v6 là đánh giá hồi cứu đã lộ.
- `threshold-calibration.csv`: số ca nhận, ca vi phạm và giới hạn rủi ro theo giả thiết binomial.
- `fea-proposals.json`: đề xuất kiểm chứng mới, chưa được chứng nhận an toàn.
- `data/`: bản sao đầu vào có checksum; dữ liệu và mô hình nguồn v4 không bị sửa.
- `executed-source/`: mã đã thực thi và khóa phụ thuộc để chạy lại.

S1–S5 đã tham gia phát triển mô hình này; sai số trên chúng không được gọi là test mới.
Không trộn dữ liệu 8 ms và 12 ms. Không nới ngưỡng để biến điều kiện thất bại thành đạt.

## Chạy lại vào một thư mục mới

Từ thư mục nghiên cứu, dùng Python/uv cùng phiên bản đã khóa:

```powershell
cd executed-source
uv sync --locked --extra campaign
uv run --locked --extra campaign python scripts/run_reliability_study.py{flag} --archive ../data/source.zip --validation-dir ../data/verification --output ../reproduction-001
```

`checksums.json` giữ nguyên biên bản đầu ra lúc fit xong. `delivery-checksums.json`
niêm phong toàn bộ gói sau khi bổ sung mã và dữ liệu tái lập. Chỉ tải mô hình joblib
do chính quy trình này tạo và đã kiểm hash.
'''
    (study / 'README.md').write_text(text, encoding='utf-8')
    write_json(study / 'delivery-checksums.json', {str(p.relative_to(study)): sha256(p)
               for p in study.rglob('*') if p.is_file() and p.name != 'delivery-checksums.json'})
    print(json.dumps({'study': str(study), 'status': 'delivery_sealed'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
