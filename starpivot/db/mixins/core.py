"""StarPivot Engine - Database core mixin"""
import sqlite3
import uuid
import json
import time
import os
from datetime import datetime, timedelta
from typing import Any, Optional


class CoreMixin:
    """Mixin providing core-related database operations."""
    
    # All methods in this mixin access self.conn, self._execute_write, etc.
    # from the parent Database class.
    
    def __init__(self, db_path: Optional[str] = None) -> None:
        """初始化数据库实例。

        Args:
            db_path: SQLite 数据库文件路径，默认使用 settings.db_path。
        """
        self._db_path = db_path or settings.db_path
        self._lock = threading.Lock()


    def init_db(self) -> None:
        """创建所有表及索引（幂等，已存在的表不会重复创建）。"""
        # 确保数据目录存在
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            for ddl in _ALL_DDL:
                conn.executescript(ddl)
            # 迁移：为已有数据库添加新列（如果不存在）
            try:
                conn.execute("ALTER TABLE agents ADD COLUMN is_system INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass  # 列已存在
            try:
                conn.execute("ALTER TABLE agents ADD COLUMN api_provider TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE agents ADD COLUMN api_key TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE agents ADD COLUMN api_model TEXT DEFAULT ''")
            except Exception:
                pass
            # 迁移：为已有数据库创建 agent_souls 表（如果不存在）
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS agent_souls ("
                    "agent_id TEXT PRIMARY KEY,"
                    "content TEXT NOT NULL DEFAULT '',"
                    "ironclad_rules TEXT NOT NULL DEFAULT '',"
                    "version INTEGER DEFAULT 1,"
                    "created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),"
                    "updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),"
                    "FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE"
                    ")"
                )
            except Exception:
                pass
            # 迁移：为已有数据库创建 agent_memories 表（如果不存在）
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS agent_memories ("
                    "id TEXT PRIMARY KEY,"
                    "agent_id TEXT NOT NULL,"
                    "user_id TEXT NOT NULL,"
                    "tier INTEGER DEFAULT 1 CHECK(tier IN (1,2,3)),"
                    "content TEXT NOT NULL,"
                    "keywords TEXT DEFAULT '',"
                    "importance REAL DEFAULT 0.5,"
                    "source TEXT DEFAULT '',"
                    "created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),"
                    "accessed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),"
                    "FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE"
                    ")"
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_memories_agent_user ON agent_memories(agent_id, user_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_memories_tier ON agent_memories(agent_id, tier)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_memories_importance ON agent_memories(agent_id, importance)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_memories_accessed ON agent_memories(agent_id, accessed_at)")
            except Exception:
                pass
            # 迁移：为 agent_memories 表添加 access_count 列
            try:
                conn.execute("ALTER TABLE agent_memories ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass
            # 迁移：为已有数据库创建 memory_relations 表（如果不存在）
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS memory_relations ("
                    "id TEXT PRIMARY KEY,"
                    "agent_id TEXT NOT NULL,"
                    "user_id TEXT NOT NULL,"
                    "entity TEXT NOT NULL,"
                    "relation TEXT NOT NULL,"
                    "target TEXT NOT NULL,"
                    "created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),"
                    "FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE"
                    ")"
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_relations_agent_user ON memory_relations(agent_id, user_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_relations_entity ON memory_relations(agent_id, user_id, entity)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_relations_relation ON memory_relations(agent_id, user_id, relation)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_relations_target ON memory_relations(agent_id, user_id, target)")
            except Exception:
                pass
            # 迁移：为已有数据库添加 is_admin 列（如果不存在）
            try:
                conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass  # 列已存在
            # 迁移：为已有数据库添加 is_developer 列（如果不存在）
            try:
                conn.execute("ALTER TABLE users ADD COLUMN is_developer INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass  # 列已存在
            # 迁移：为已有数据库添加等级字段
            try:
                conn.execute("ALTER TABLE users ADD COLUMN opc_level INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE users ADD COLUMN dev_level INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass
            # 迁移：为 AI 智能体市场添加买卖/租赁价格字段
            try:
                conn.execute("ALTER TABLE agents ADD COLUMN for_sale_price REAL DEFAULT NULL")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE agents ADD COLUMN for_rent_price REAL DEFAULT NULL")
            except Exception:
                pass
            # 迁移：更新 transactions 表的 CHECK 约束，添加 agent_transfer 类型
            try:
                conn.execute("ALTER TABLE transactions ADD COLUMN _migrate_dummy INTEGER DEFAULT 0")
            except Exception:
                pass
            # SQLite 不能直接改 CHECK，所以只更新 DDL 供新库使用
            # 对已有数据库，使用 'payment' 类型替代 agent_transfer


    def conn(self):
        """获取数据库连接的上下文管理器。

        每次调用返回一个新的 sqlite3.Connection，自动提交/回滚。
        """
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


    def _new_id() -> str:
        """生成 UUID4 主键。"""
        return uuid.uuid4().hex


    def _short_id(prefix: str = "") -> str:
        """生成短ID：前缀+12位随机（如 TK3k7m2pRq9xW）。"""
        chars = string.ascii_letters + string.digits
        return prefix + ''.join(random.choices(chars, k=12))


    def _generate_id(prefix: str = "ZH") -> str:
        """生成带前缀的14位短ID（2位前缀 + 12位随机字符）。"""
        chars = string.ascii_letters + string.digits  # a-z, A-Z, 0-9
        return prefix + ''.join(random.choices(chars, k=12))


    def _row_to_dict(row):
        """将 sqlite3.Row 转换为 dict，None 原样返回。"""
        return dict(row) if row else None


    def _execute_write(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """线程安全地执行写操作。"""
        with self._lock:
            with self.conn() as conn:
                return conn.execute(sql, params)

