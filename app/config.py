from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"

    # Meta / Messenger
    meta_verify_token: str = "change-me"
    meta_app_secret: str = ""
    page_access_token: str = ""

    # Ha tang
    database_url: str = "postgresql+asyncpg://alpha3s:alpha3s@db:5432/alpha3s"
    redis_url: str = "redis://redis:6379/0"

    # LLM (DeepSeek)
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"

    # Embedding local
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384

    # Human handoff (issue #7): thong bao Telegram khi escalate
    telegram_bot_token: str = ""
    telegram_admin_chat_id: str = ""
    # admin_api_token: DA XOA (issue #9, Bat 1) - la token tinh dung chung cu,
    # thay the hoan toan boi dang nhap that (staff_users/staff_sessions) tu
    # issue #8 Bat 4. Neu bien ADMIN_API_TOKEN con trong file .env cua ai do,
    # khong sao ca - pydantic-settings voi extra="ignore" se tu bo qua, khong loi.

    # Dashboard Next.js (issue #8): danh sach origin duoc phep goi API, cach nhau boi dau phay
    dashboard_cors_origins: str = "http://localhost:3000"

    # Kenh khach hang du phong qua Telegram (khac han telegram_bot_token o tren,
    # cai do la bot ADMIN nhan thong bao/lenh - bot nay tiep khach truc tiep)
    telegram_customer_bot_token: str = ""

    # Lop NLU (issue #12) tich hop vao orchestrator - feature flag, MAC DINH TAT.
    # Khi bat: NLU Router chay THEM (khong thay the) flow hien tai, chi bo sung
    # hint/context cho LLM - xem app/services/nlu_hint.py. Loi trong duong NLU
    # (bat ky dau) deu bi bat va bo qua LANG LE, KHONG BAO GIO lam vo flow tra
    # loi chinh - xem NLU-INTEGRATION-GUIDE.md "Orchestrator Responsibilities".
    enable_nlu_router: bool = False


settings = Settings()
