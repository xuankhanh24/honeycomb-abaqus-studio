from service.cloud_api import create_app

app = create_app()
app.frontend("/", directory="dist", fallback="index.html", check_dir=False)
