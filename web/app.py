from pathlib import Path

from service.cloud_api import create_app

app = create_app()
app.frontend("/", directory=str(Path(__file__).parent / "public"), fallback="index.html")
