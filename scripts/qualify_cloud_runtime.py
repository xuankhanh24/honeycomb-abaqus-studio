"""Collect genuine Linux CAE/datacheck/Explicit/ODB evidence, never synthesize qualification."""

import argparse
import json
import os
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abaqus", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "posix":
        raise SystemExit("blocked_environment: Linux qualification requires Linux")
    root = Path.cwd()
    output = root / "output/native-qualification"
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "platform": "linux",
        "solver_success": False,
        "linux_checkout": False,
        "features": [],
        "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
    }

    def command(label, arguments, timeout):
        with (output / (label + ".log")).open("w") as log:
            subprocess.run(
                [str(args.abaqus), *arguments],
                cwd=output,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=timeout,
            )

    try:
        command("release", ["information=release"], 60)
        adapter = root / "src/honeycomb_studio/adapters/cloud_probe.py"
        command("cae", ["cae", "noGUI=" + str(adapter)], 300)
        report["features"].append("cae")
        command(
            "datacheck",
            ["job=CloudProbe_check", "input=CloudProbe.inp", "datacheck", "interactive", "cpus=4"],
            300,
        )
        command("solver", ["job=CloudProbe", "interactive", "cpus=4", "double=both"], 600)
        status = (output / "CloudProbe.sta").read_text(errors="replace")
        if "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" not in status:
            raise RuntimeError("Explicit did not confirm completion")
        probe = output / "read_odb.py"
        probe.write_text(
            "import json,sys\nfrom odbAccess import openOdb\no=openOdb('CloudProbe.odb',readOnly=True)\nassert len(o.steps['Impact'].frames)>1\njson.dump({'python':sys.version,'frames':len(o.steps['Impact'].frames)},open('odb-reopen.json','w'))\no.close()\n"
        )
        command("odb", ["python", str(probe)], 120)
        report.update(
            solver_success=True,
            linux_checkout=True,
            features=["cae", "explicit"],
            odb_reopened=True,
            odb=json.loads((output / "odb-reopen.json").read_text()),
        )
    finally:
        (output / "qualification.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
