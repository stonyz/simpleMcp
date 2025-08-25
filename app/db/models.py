from sqlalchemy import Column, Integer, String, Text, UniqueConstraint, Index
from app.db import Base

class OpenAPIFile(Base):
    __tablename__ = "openapi_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    orgid = Column(String(64), nullable=False, index=True)
    appid = Column(String(64), nullable=False, index=True)
    title = Column(String(256), nullable=False, index=True)
    version = Column(String(64), nullable=True)
    openapi_yaml = Column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("orgid", "appid", "title", "version", name="uq_org_app_title_ver"),
        Index("idx_org_app", "orgid", "appid"),
    )
