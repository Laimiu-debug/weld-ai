"""SQLite 数据库会话管理（单机，WAL 模式）。

会话策略：单例共享 session（应用生命周期内复用），
避免每次 get_session() 新建导致 WAL 连接泄漏。
测试/批处理可用 session_scope() 上下文管理器自动关闭。
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# 默认数据库文件：用户目录下，单机便于备份/迁移
DEFAULT_DB_DIR = Path.home() / ".weldai"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "weldai.db"

_engine = None
_SessionLocal = None
_shared_session: Session | None = None


def init_db(db_path: Path | str | None = None, echo: bool = False):
    """初始化数据库引擎并建表。"""
    global _engine, _SessionLocal, _shared_session
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # SQLite 启用 WAL：多读单写，单机友好
    url = f"sqlite:///{path}"
    _engine = create_engine(url, echo=echo, future=True)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    _shared_session = None  # 重置共享会话

    # 启用 WAL 与外键
    from sqlalchemy import event

    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    # 建表
    from . import models  # noqa: F401  (确保模型已注册)
    from .models import Base

    Base.metadata.create_all(_engine)
    _migrate(_engine)
    return _engine


def _migrate(engine) -> None:
    """轻量级 schema 迁移：检测已有表缺失的列并补齐。

    单机 SQLite 场景下，create_all 只建新表不改旧表结构。
    新增字段时在此声明，实现平滑升级（避免用户删除旧库）。
    用 PRAGMA user_version 记录 schema 版本，防止跨版本不匹配。
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    # 当前代码支持的 schema 版本（每次新增字段/表时递增）
    CURRENT_SCHEMA_VERSION = 2  # v1=初始 v2=+doc_meta/last_work_date

    with engine.connect() as conn:
        version = conn.execute(text("PRAGMA user_version")).scalar() or 0
        # (表名, 列名, 列定义SQL) —— 新增字段在此登记
        migrations = [
            ("welders", "last_work_date", "DATE"),
            ("procedures", "doc_meta", "JSON"),
        ]
        for table, column, coltype in migrations:
            if table not in insp.get_table_names():
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            if column not in existing:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
                )
        # 记录已应用的 schema 版本
        conn.execute(text(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}"))
        conn.commit()


def get_session() -> Session:
    """获取共享数据库会话（单例，应用生命周期内复用）。

    避免每次调用新建 session 导致连接泄漏。
    需先调用 init_db()。应用退出时调用 close_session()。
    """
    global _shared_session
    if _SessionLocal is None:
        init_db()
    if _shared_session is None:
        _shared_session = _SessionLocal()
    return _shared_session


def close_session() -> None:
    """关闭共享会话（应用退出时调用，释放 WAL 连接）。"""
    global _shared_session
    if _shared_session is not None:
        _shared_session.close()
        _shared_session = None


@contextmanager
def session_scope() -> Session:
    """会话上下文管理器（测试/批处理用，自动关闭）。

    用法: with session_scope() as s: ...
    """
    if _SessionLocal is None:
        init_db()
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
