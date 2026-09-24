"""Start everything with one command:  python run.py
Web server (API + Mini App + admin panel) and the Telegram bot run in the same process."""
import uvicorn

from backend.config import settings

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host=settings.HOST, port=settings.PORT, proxy_headers=True,
                forwarded_allow_ips="*", log_level="info")
