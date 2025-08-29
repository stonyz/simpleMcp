from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # MySQL
    MYSQL_HOST: str = Field("localhost", description="MySQL host")
    MYSQL_PORT: int = Field(3306, description="MySQL port")
    MYSQL_USER: str = Field(..., description="MySQL user")
    MYSQL_PASSWORD: str = Field(..., description="MySQL password")
    MYSQL_DB: str = Field(..., description="MySQL database")

    # 默认全局 API Token（可被 org/app 定义的覆盖机制替代）
    API_TOKEN: Optional[str] = Field(None, description="Default Bearer token for upstream APIs")

    # 服务
    APP_NAME: str = "Dynamic MCP Server"
    DEBUG: bool = False
    log_level:str = "DEBUG"
    log_file_size:int = 10 * 1024 * 1024
    enable_console: bool = Field(True, description="Enable console logging")

    # Pydantic v2 配置
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

# 实例化
settings = Settings()
