from sqlalchemy import Column, Integer, String, Text, DATETIME, TIMESTAMP, UniqueConstraint, Index, func, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
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
    update_at = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


    __table_args__ = (
        UniqueConstraint("tenant", "orgid", "appid", "fileId", name="uq_ta_org_app_fileId"),
        Index("idx_ta_org_app", "tenant", "orgid", "appid"),
    )


class MCPCredential(Base):
    __tablename__ = 'mcp_credentials'
    id = Column(String(32), primary_key=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=False, default='')
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    token_prefix = Column(String(16), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    expires_at = Column(DATETIME, nullable=True)
    created_at = Column(DATETIME, nullable=False)
    updated_at = Column(DATETIME, nullable=False)
    last_used_at = Column(DATETIME, nullable=True)
    rules = relationship('MCPAccessRule', cascade='all, delete-orphan', lazy='selectin', order_by='MCPAccessRule.id')


class MCPAccessRule(Base):
    __tablename__ = 'mcp_access_rules'
    id = Column(Integer, primary_key=True, autoincrement=True)
    credential_id = Column(String(32), ForeignKey('mcp_credentials.id', ondelete='CASCADE'), nullable=False, index=True)
    tenant = Column(String(63), nullable=False)
    org = Column(String(64), nullable=True)
    app = Column(String(64), nullable=True)
    services = Column(JSON, nullable=True)
    operations = Column(JSON, nullable=False)
