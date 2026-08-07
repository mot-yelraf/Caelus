from caelus.app import create_app
import os

app = create_app()

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("CAELUS_HTTP_PORT", "8767"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
