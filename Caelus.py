from caelus.app import create_app
import os

app = create_app()

if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("CAELUS_HTTP_HOST", "0.0.0.0")
    port = int(os.environ.get("CAELUS_HTTP_PORT", "8767"))
    uvicorn.run(app, host=host, port=port, log_level="info")
