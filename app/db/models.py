from sqlalchemy import Column, Integer, String, Text, DATETIME, TIMESTAMP, UniqueConstraint, Index, func, text
from app.db import Base

class OpenAPIFile(Base):
    __tablename__ = "openapi_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant = Column(String(63), nullable=False)
    orgid = Column(String(64), nullable=False)
    appid = Column(String(64), nullable=False)
    fileId = Column(String(64), nullable=False)
    fileName = Column(String(256), nullable=False)
    title = Column(String(256), nullable=False)
    version = Column(String(64), nullable=True)
    openapi_yaml = Column(Text, nullable=False)
    # Add auth column to store optional auth data
    auth = Column(Text, nullable=True)
    create_at = Column(DATETIME, nullable=False)
    update_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"))


    __table_args__ = (
        UniqueConstraint("tenant", "orgid", "appid", "fileId", name="uq_ta_org_app_fileId"),
        Index("idx_ta_org_app", "tenant", "orgid", "appid"),
    )