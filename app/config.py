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

    # DB connection pool (I-B M0.2, CA-REVIEW-M0-DEV §9): min/max MOI process + command timeout.
    # Baseline min=1/max=5 moi process (2 API worker + 1 arq ~ 15 conn < default 100) - do roi chinh.
    db_pool_min_size: int = 1
    db_pool_max_size: int = 5
    db_command_timeout: float = 30.0

    # RBAC strict mode (I-B M0.4, CA-REVIEW-M0-DEV-002 §7): MAC DINH false cho dev rollout
    # (backward-compat degrade). Production SAU khi 016+seed ap -> dat true: require_permission
    # KHONG degrade nua, va startup fail neu RBAC provisioned nhung catalog/mapping thieu.
    rbac_strict: bool = False

    # Session TTL (I-B M0.5, CA-REVIEW-M0-DEV-003 §8): giam tu 7 ngay -> 48h cho auth/session
    # temporary exception (localStorage). Cau hinh duoc de production dat <=48h.
    session_ttl_hours: int = 48

    # LLM (DeepSeek)
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"  # deepseek-chat bi DeepSeek deprecate (25/7) -> v4-flash

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

    # Semantic Router (tang fallback dung model mpnet ~1.1GB RAM) - MAC DINH TAT
    # theo quyet dinh PO 23/7 (xem docs/KB_NLU_RESOURCE_ASSESSMENT-VI.md PA2-5a):
    # Pattern Router + High-precision Rules + Entity Extraction van chay du
    # (94.6% chinh xac trong pham vi phu ~40% cau), cau khong khop se KHONG co
    # hint intent (LLM tu xu ly nhu truoc #12). Khi TAT: model mpnet KHONG BAO
    # GIO duoc load -> tiet kiem ~1.1GB RAM cua worker. Bat lai neu sau nay
    # quantize model (PA2-5d) hoac VPS du RAM.
    enable_semantic_router: bool = False

    # I-B M1 (Slice 4): reliable order command bus. MAC DINH TAT — canary bat sau qua production
    # gate rieng (CA release decision). Khi TAT: 3 duong tao don giu nguyen legacy (khong doi hanh vi).
    # Khi BAT: route qua command service (effective-once + atomic outbox + deterministic receipt).
    m1_reliable_order_command: bool = False

    # I-B M2 (Order and Inventory Correctness). MAC DINH TAT — canary/rollout theo phase (§15.6).
    # m2_inventory_ledger: dual-write ledger/reservation/balance (order.create reserve atomic; shadow).
    # m2_order_transitions: shared transition service + matrix guard cho lifecycle command.
    # m2_balance_authority: balance thanh nguon quyet dinh availability/reserve (Phase C) — bat SAU cung.
    m2_inventory_ledger: bool = False
    m2_order_transitions: bool = False
    m2_balance_authority: bool = False
    # m3_delivered_lifecycle: mở transition delivered/retry/cancel-sau-delivery-failed (M3-S1).
    # OFF (default) = matrix M2 nguyên trạng; missing config -> False (fail-safe).
    m3_delivered_lifecycle: bool = False
    # m3_utm_attribution: ghi UTM (đã validate) xuống orders khi order.create có utm (M3-S2).
    # OFF = không ghi (cột NULL) — validate vẫn deterministic ở registry.
    m3_utm_attribution: bool = False
    # m3_outbound_dispatcher: customer notify đi qua dispatcher (consent check + approved template)
    # thay vì payload text trực tiếp (M3-S5). OFF = đường M2 nguyên trạng. Dedupe key giữ nguyên.
    m3_outbound_dispatcher: bool = False


settings = Settings()
