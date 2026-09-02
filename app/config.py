from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="METER_")

    ollama_url: str = "http://localhost:11434/api/generate"
    ollama_model: str = "glm-ocr:latest"
    ollama_timeout: float = 300.0

    csv_path: str = "data/Cherry Data.csv"
    out_dir: str = "out"

    max_upload_bytes: int = 10 * 1024 * 1024  # 10MB
    allowed_content_types: tuple[str, ...] = ("image/jpeg", "image/png", "image/webp")

    max_concurrent_ocr: int = 1  # ollama serializes anyway; cap in-flight requests here


settings = Settings()
