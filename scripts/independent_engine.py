"""Background entry point for the demand-only Windows engine task."""
import os
import sys
from pathlib import Path

directory = Path(os.environ['LOCALAPPDATA']) / 'HoneycombStudio' / 'logs'
directory.mkdir(parents=True, exist_ok=True)
log = (directory / 'engine.log').open('a', encoding='utf-8', buffering=1)
sys.stdout = log
sys.stderr = log
print('Independent engine starting; pid=%s' % os.getpid(), flush=True)


from honeycomb_studio.cli import main  # noqa: E402

main()
