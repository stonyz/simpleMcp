from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker, declarative_base
from contextlib import contextmanager
from app.config import settings

DATABASE_URL = settings.DATABASE_URL
database_url = make_url(DATABASE_URL)
if database_url.get_backend_name() != "sqlite":
    raise ValueError("DATABASE_URL must use SQLite (sqlite:///path/to/database.db)")

in_memory = database_url.database in (None, "", ":memory:")
if not in_memory:
    Path(database_url.database).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    **({"poolclass": StaticPool} if in_memory else {}),
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

#for others.
@contextmanager
def get_db_context():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except:
        db.rollback()  # 事务失败时回滚，释放锁
        raise  # 继续抛出异常，确保上层代码可以捕获错误
    finally:
        db.close()
