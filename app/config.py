from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # SQLite
    DATABASE_URL: str = Field("sqlite:///./data/mcp.db", description="SQLite database URL")

    # 默认全局 API Token（可被 org/app 定义的覆盖机制替代）
    API_TOKEN: Optional[str] = Field(None, description="Default Bearer token for upstream APIs")
    
    # 授权Tokens列表
    AUTH_TOKENS: List[str] = Field(default_factory=list, description="List of valid authorization tokens")

    # 代理配置
    PROXY_URL: Optional[str] = Field(None, description="Proxy URL for outgoing requests")
    PROXY_RULES: Optional[str] = Field(None, description="Comma-separated list of URL patterns that require proxy")

    # 应用配置
    APP_NAME: str = "Dynamic MCP Server"
    DEBUG: bool = False
    log_level: str = "DEBUG"
    log_file_size: int = 10 * 1024 * 1024
    enable_console: bool = Field(True, description="Enable console logging")

    # Pydantic v2 配置
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 兼容旧 .env 中不再使用的 MYSQL_* 配置
    )

# 实例化
settings = Settings()
