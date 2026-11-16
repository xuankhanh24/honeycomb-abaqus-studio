# Frozen surrogate validation extraction

Run 43730004401 solved V11-02 successfully, then spent about 99 minutes exporting field matrices before the execution budget interrupted extraction. Archival was still uploading 1 GiB ODB volumes when the 330-minute Actions job limit cancelled the runner. The original release has no final completeness manifest, so it cannot be treated as a verified completed ODB archive.

Locked surrogate verification shards now use a dedicated `validation_metrics` extraction profile. It reads the original history channels, evaluates rear displacement and STATUS on every native frame, and sums native CNORMF/CSHEARF vectors on the impactor at every frame. It avoids serializing the complete S/U/PEEQ matrices through NumPy spool files. The normal exporter remains the default for other jobs. The profile records its narrower field scope in `inventory.json`.

The bulk rear reader preserves the reference algorithm's STATUS < 0.5 threshold, displacement relative to the first frame, connectivity to the clamp and per-instance maximum deletion counts. Tests compare its complete rows and summary against the original reader with bulk access available and with the native double-precision fallback. Contact vectors remain an independent check against inertial force. No material, geometry, mesh, contact or solver-deck generator is changed; numerical quality gates remain unchanged.

The aggregation requirement now distinguishes a finished verification experiment from a batch where every design is eligible for training. A numerically valid simulation with rear deletion is usable evidence that a surrogate screen failed. It remains ineligible under the application's existing intact-bottom training rule. Validation aggregation requires every archive, full native history, sampled earlier horizon and internally consistent SEA calculation; it reports the observed deletion outcomes without overriding them.

The workflow permits only the explicitly authorized V11 recovery job on branch `fix/v11-postprocess-timeout`, with `recover=true`. Main retains its existing admission path. Recovery preserves the four archived completed/reviewed shards and reruns only the interrupted shard. Failure artifact retention now also covers cancellation.

Regression signal:

```text
python -m pytest -q tests/test_validation_metrics_export.py tests/test_validation_completion.py
```

The exporter regression invokes the real adapter entry point. It failed before the patch because validation traversed full stress/displacement arrays. It passes with all history samples, rear frames and native contact sums retained. Additional tests keep invalid or missing verification evidence red, including inconsistent SEA and wrong horizon time.
