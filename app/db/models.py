from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, UniqueConstraint, Index, func, text
from app.db import Base

class OpenAPIFile(Base):
    __tablename__ = "openapi_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    orgid = Column(String(64), nullable=False)
    appid = Column(String(64), nullable=False)
    fileId = Column(String(64), nullable=False)
    fileName = Column(String(256), nullable=False)
    title = Column(String(256), nullable=False)
    version = Column(String(64), nullable=True)
    openapi_yaml = Column(Text, nullable=False)
    create_at = Column(TIMESTAMP, nullable=False)
    update_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"))


    __table_args__ = (
        UniqueConstraint("orgid", "appid", "fileId", name="uq_org_app_fileId"),
        Index("idx_org_app", "orgid", "appid"),
    )
