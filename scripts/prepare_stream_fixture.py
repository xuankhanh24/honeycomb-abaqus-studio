"""Copy bounded samples of existing native Parquet fields; never alter originals."""

import argparse
import hashlib
import json
import shutil
import tarfile
from pathlib import Path

import pyarrow.parquet as pq


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    output = Path("output/native-stream-fixture")
    output.mkdir()
    fields = []
    for name in ("U", "S", "PEEQ"):
        frames = sorted((args.source / "fields/Impact" / name).glob("frame=*"))
        if len(frames) < 2:
            raise ValueError("Expected native first/last frames for " + name)
        for frame in (frames[0], frames[-1]):
            source = next(iter(sorted(frame.glob("*.parquet"))))
            digest = sha(source)
            relative = source.relative_to(args.source)
            target = output / "extracted" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            assert sha(target) == digest == sha(source)
            with pq.ParquetFile(target) as parquet:
                meta = json.loads(parquet.schema_arrow.metadata[b"honeycomb"])
                rows = parquet.metadata.num_rows
            fields.append({"path": target.relative_to(output).as_posix(), "sha256": digest,
                           "bytes": source.stat().st_size, "rows": rows, "meta": meta})
    provenance = {"kind": "existing-native-field-transport-sample", "source": "Windows Abaqus 2017 hexagonal 7 J circular-clamp reference",
                  "source_run_id": "b42c56b9a0c61_r00001_a0784de3", "solver_executed": False,
                  "complete_field_dataset": False, "selection": "one first chunk for first/last frame of U/S/PEEQ",
                  "files": fields}
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    with tarfile.open("output/native-field-inputs.tar", "w") as bundle:
        for file in sorted(output.rglob("*")):
            if file.is_file():
                bundle.add(file, arcname=file.relative_to(output).as_posix(), recursive=False)
    print(json.dumps({"files": len(fields), "rows": sum(f["rows"] for f in fields),
                      "bytes": sum(f["bytes"] for f in fields),
                      "fixture_sha256": sha(Path("output/native-field-inputs.tar"))}))


if __name__ == "__main__":
    main()
