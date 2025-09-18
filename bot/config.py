import os
from typing import Optional

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    # dotenv is optional; ignore if not installed
    pass


class Settings:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        # Example: mysql+asyncmy://user:password@localhost:3306/sdu_hw
        "",
    )
    SDU_LOGIN_URL: str = os.getenv("SDU_LOGIN_URL", "https://my.sdu.edu.kz/loginAuth.php")
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Almaty")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    ADMIN_IDS: list[int] = [
        int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()
    ]


settings = Settings()


