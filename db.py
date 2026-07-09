"""
AI Agent 工具平台 数据库层
-----------------------
线程安全的 SQLite 数据库封装，管理6张核心表。
提供上下文管理器连接、各表 CRUD、余额原子操作、全局单例。
"""

import random
import sqlite3
import string
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from config import settings



# ═══════════════════════════════════════════════════════════════════
# 建表 DDL — 与 store/schema.sql 完全一致
# ═══════════════════════════════════════════════════════════════════
_DDL_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    username        TEXT    NOT NULL,
    password_hash   TEXT    NOT NULL,
    balance_cents   REAL    NOT NULL DEFAULT 0,
    is_admin        INTEGER NOT NULL DEFAULT 0,
    is_developer    INTEGER NOT NULL DEFAULT 0,
    opc_level       INTEGER NOT NULL DEFAULT 0,
    dev_level       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
"""

_DDL_AGENTS = """
CREATE TABLE IF NOT EXISTS agents (
    id              TEXT PRIMARY KEY,
    user_id         TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    system_prompt   TEXT    NOT NULL DEFAULT '',
    tier            TEXT    NOT NULL DEFAULT '一级',
    status          TEXT    NOT NULL DEFAULT 'running' CHECK(status IN ('running','paused','dead')),
    balance_cents   REAL    NOT NULL DEFAULT 0,
    is_system       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_agents_user_id ON agents(user_id);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_tier ON agents(tier);
CREATE INDEX IF NOT EXISTS idx_agents_is_system ON agents(is_system);
"""

_DDL_SERVICES = """
CREATE TABLE IF NOT EXISTS services (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    price_cents     REAL    NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive')),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_services_agent_id ON services(agent_id);
CREATE INDEX IF NOT EXISTS idx_services_status ON services(status);
"""

_DDL_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS transactions (
    id              TEXT PRIMARY KEY,
    from_id         TEXT,
    to_id           TEXT,
    amount_cents    REAL    NOT NULL,
    type            TEXT    NOT NULL CHECK(type IN ('recharge','payment','refund','deposit','rental','withdrawal','rental_payment','agent_transfer')),
    description     TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_transactions_from_id ON transactions(from_id);
CREATE INDEX IF NOT EXISTS idx_transactions_to_id ON transactions(to_id);
CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(type);
CREATE INDEX IF NOT EXISTS idx_transactions_created ON transactions(created_at);
"""

_DDL_MESSAGES = """
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT    NOT NULL,
    role            TEXT    NOT NULL CHECK(role IN ('user','assistant','tool')),
    content         TEXT    NOT NULL DEFAULT '',
    turn_seq        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_agent_id ON messages(agent_id);
CREATE INDEX IF NOT EXISTS idx_messages_turn_seq ON messages(agent_id, turn_seq);
"""

_DDL_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT    NOT NULL,
    action          TEXT    NOT NULL,
    detail          TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_audit_log_agent_id ON audit_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at);
"""

_DDL_TASKS = """
CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    title           TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    reward          REAL    NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','CLAIMED','COMPLETED','CANCELLED')),
    assignee_id     TEXT,
    creator_id      TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (assignee_id) REFERENCES agents(id) ON DELETE SET NULL,
    FOREIGN KEY (creator_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_creator ON tasks(creator_id);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee_id);
"""

_DDL_AUCTIONS = """
CREATE TABLE IF NOT EXISTS auctions (
    id              TEXT PRIMARY KEY,
    seller_id       TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    starting_price  REAL    NOT NULL DEFAULT 0,
    current_bid     REAL    NOT NULL DEFAULT 0,
    winner_id       TEXT,
    status          TEXT    NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','SETTLED','CANCELLED')),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    ended_at        TEXT,
    FOREIGN KEY (seller_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_auctions_seller_id ON auctions(seller_id);
CREATE INDEX IF NOT EXISTS idx_auctions_status ON auctions(status);
CREATE INDEX IF NOT EXISTS idx_auctions_created_at ON auctions(created_at);
"""

_DDL_BIDS = """
CREATE TABLE IF NOT EXISTS bids (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    auction_id      TEXT    NOT NULL,
    bidder_id       TEXT    NOT NULL,
    amount          REAL    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (auction_id) REFERENCES auctions(id) ON DELETE CASCADE,
    FOREIGN KEY (bidder_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_bids_auction_id ON bids(auction_id);
CREATE INDEX IF NOT EXISTS idx_bids_bidder_id ON bids(bidder_id);
"""

_DDL_BOOKS = """
CREATE TABLE IF NOT EXISTS books (
    id              TEXT PRIMARY KEY,
    author_id       TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    content         TEXT    NOT NULL DEFAULT '',
    price           REAL    NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('PUBLISHED','DRAFT')),
    download_count  INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (author_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_books_author_id ON books(author_id);
CREATE INDEX IF NOT EXISTS idx_books_status ON books(status);
"""

_DDL_USED_GOODS = """
CREATE TABLE IF NOT EXISTS used_goods (
    id              TEXT PRIMARY KEY,
    seller_id       TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    category        TEXT    NOT NULL DEFAULT 'tool' CHECK(category IN ('tool','script','config','knowledge')),
    price           REAL    NOT NULL DEFAULT 0,
    original_value  REAL    NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'ONSALE' CHECK(status IN ('ONSALE','SOLD')),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (seller_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_used_goods_seller_id ON used_goods(seller_id);
CREATE INDEX IF NOT EXISTS idx_used_goods_category ON used_goods(category);
CREATE INDEX IF NOT EXISTS idx_used_goods_status ON used_goods(status);
"""

_DDL_RENTALS = """
CREATE TABLE IF NOT EXISTS rentals (
    id                  TEXT PRIMARY KEY,
    owner_id            TEXT    NOT NULL,
    name                TEXT    NOT NULL,
    description         TEXT    NOT NULL DEFAULT '',
    price_per_hour      REAL    NOT NULL DEFAULT 0,
    max_duration_hours  INTEGER NOT NULL DEFAULT 24,
    status              TEXT    NOT NULL DEFAULT 'AVAILABLE' CHECK(status IN ('AVAILABLE','RENTED')),
    renter_id           TEXT,
    rented_at           TEXT,
    return_by           TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (owner_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rentals_owner_id ON rentals(owner_id);
CREATE INDEX IF NOT EXISTS idx_rentals_status ON rentals(status);
"""

_DDL_STOCKS_PORTFOLIOS = """
CREATE TABLE IF NOT EXISTS stocks_portfolios (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    shares          REAL    NOT NULL DEFAULT 0,
    avg_cost        REAL    NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_stocks_portfolios_agent_id ON stocks_portfolios(agent_id);
CREATE INDEX IF NOT EXISTS idx_stocks_portfolios_symbol ON stocks_portfolios(symbol);
"""

_DDL_STOCK_TRADES = """
CREATE TABLE IF NOT EXISTS stock_trades (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    shares          REAL    NOT NULL,
    price           REAL    NOT NULL,
    total_cost      REAL    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_stock_trades_agent_id ON stock_trades(agent_id);
CREATE INDEX IF NOT EXISTS idx_stock_trades_symbol ON stock_trades(symbol);
"""

_DDL_AGENT_SKILLS = """
CREATE TABLE IF NOT EXISTS agent_skills (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT    NOT NULL,
    skill_id        TEXT    NOT NULL,
    source          TEXT    NOT NULL DEFAULT 'gift',
    is_equipped     INTEGER NOT NULL DEFAULT 1,
    acquired_at     TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_agent_skills_agent_id ON agent_skills(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_skills_skill_id ON agent_skills(skill_id);
CREATE INDEX IF NOT EXISTS idx_agent_skills_equipped ON agent_skills(agent_id, is_equipped);
"""

_DDL_ROLES = """
CREATE TABLE IF NOT EXISTS roles (
    id              TEXT PRIMARY KEY,
    name            TEXT    NOT NULL,
    category        TEXT    NOT NULL DEFAULT '',
    description     TEXT    NOT NULL DEFAULT '',
    system_prompt   TEXT    NOT NULL DEFAULT '',
    emoji           TEXT    NOT NULL DEFAULT '',
    tier            TEXT    NOT NULL DEFAULT 'template',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
"""

_DDL_SHOWCASES = """
CREATE TABLE IF NOT EXISTS showcases (
    id              TEXT PRIMARY KEY,
    user_id         TEXT    NOT NULL,
    agent_id        TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    content         TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_showcases_user_id ON showcases(user_id);
CREATE INDEX IF NOT EXISTS idx_showcases_created_at ON showcases(created_at);
"""

_DDL_SKILL_DEFINITIONS = """
CREATE TABLE IF NOT EXISTS skill_definitions (
    id TEXT PRIMARY KEY,
    developer_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    star_level INTEGER NOT NULL DEFAULT 1 CHECK(star_level BETWEEN 1 AND 5),
    price_cents REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','disabled')),
    review_comment TEXT DEFAULT '',
    reviewer_id TEXT,
    reviewed_at TEXT,
    download_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (developer_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_skill_defs_dev ON skill_definitions(developer_id);
CREATE INDEX IF NOT EXISTS idx_skill_defs_status ON skill_definitions(status);
CREATE INDEX IF NOT EXISTS idx_skill_defs_category ON skill_definitions(category);
"""

_DDL_SKILL_RATINGS = """
CREATE TABLE IF NOT EXISTS skill_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    comment TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (skill_id) REFERENCES skill_definitions(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(skill_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_skill_ratings_skill ON skill_ratings(skill_id);
"""

_DDL_SETTLEMENT_REQUESTS = """
CREATE TABLE IF NOT EXISTS settlement_requests (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    amount_cents REAL NOT NULL,
    balance_before REAL NOT NULL,
    balance_after REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','completed')),
    admin_comment TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    processed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_settlement_user ON settlement_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_settlement_status ON settlement_requests(status);
"""

_DDL_INVITATION_CODES = """
CREATE TABLE IF NOT EXISTS invitation_codes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    owner_id    TEXT NOT NULL,
    use_count   INTEGER DEFAULT 0,
    max_uses    INTEGER DEFAULT 999999,
    is_active   INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_invitation_codes_code ON invitation_codes(code);
CREATE INDEX IF NOT EXISTS idx_invitation_codes_owner ON invitation_codes(owner_id);
"""

_DDL_USER_PROFILES = """
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY,
    company_name TEXT DEFAULT '',
    industry TEXT DEFAULT '',
    role TEXT DEFAULT '',
    preferences TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
"""

_DDL_USER_OUTPUTS = """
CREATE TABLE IF NOT EXISTS user_outputs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    title TEXT DEFAULT '',
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_user_outputs_user_id ON user_outputs(user_id);
CREATE INDEX IF NOT EXISTS idx_user_outputs_created ON user_outputs(created_at);
"""

_DDL_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    expires_at  TEXT NOT NULL,
    last_active TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""

_DDL_MARKETPLACE_TOOLS = """
CREATE TABLE IF NOT EXISTS marketplace_tools (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    author_id       TEXT,
    category        TEXT,
    stars           INTEGER DEFAULT 0,
    downloads       INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'pending',  -- pending/approved/rejected
    mcp_server_code TEXT,                    -- MCP Server 代码
    config_json     TEXT,                    -- JSON 配置
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_marketplace_tools_status ON marketplace_tools(status);
CREATE INDEX IF NOT EXISTS idx_marketplace_tools_category ON marketplace_tools(category);
CREATE INDEX IF NOT EXISTS idx_marketplace_tools_stars ON marketplace_tools(stars);
"""

_DDL_AGENT_SOULS = """
CREATE TABLE IF NOT EXISTS agent_souls (
    agent_id        TEXT PRIMARY KEY,
    content         TEXT NOT NULL DEFAULT '',
    ironclad_rules  TEXT NOT NULL DEFAULT '',
    version         INTEGER DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
"""

_DDL_AGENT_MEMORIES = """
CREATE TABLE IF NOT EXISTS agent_memories (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    tier            INTEGER DEFAULT 1 CHECK(tier IN (1, 2, 3)),
    content         TEXT NOT NULL,
    keywords        TEXT DEFAULT '',
    importance      REAL DEFAULT 0.5,
    source          TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    accessed_at     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_agent_memories_agent_user ON agent_memories(agent_id, user_id);
CREATE INDEX IF NOT EXISTS idx_agent_memories_tier ON agent_memories(agent_id, tier);
CREATE INDEX IF NOT EXISTS idx_agent_memories_importance ON agent_memories(agent_id, importance);
CREATE INDEX IF NOT EXISTS idx_agent_memories_accessed ON agent_memories(agent_id, accessed_at);
"""

_DDL_AI_MEMORIES = """
CREATE TABLE IF NOT EXISTS ai_memories (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT    NOT NULL,
    user_id         TEXT    NOT NULL,
    key             TEXT    NOT NULL,
    value           TEXT    NOT NULL,
    source          TEXT,
    confidence      INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_ai_memories_agent_user ON ai_memories(agent_id, user_id);
CREATE INDEX IF NOT EXISTS idx_ai_memories_key ON ai_memories(agent_id, user_id, key);
"""

_DDL_AI_CONVERSATIONS = """
CREATE TABLE IF NOT EXISTS ai_conversations (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT    NOT NULL,
    user_id         TEXT    NOT NULL,
    summary         TEXT,
    key_points      TEXT,
    started_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    ended_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_conversations_agent_user ON ai_conversations(agent_id, user_id);
CREATE INDEX IF NOT EXISTS idx_ai_conversations_started ON ai_conversations(started_at);
"""

_DDL_MARKETPLACE_REVIEWS = """
CREATE TABLE IF NOT EXISTS marketplace_reviews (
    id          TEXT PRIMARY KEY,
    tool_id     TEXT,
    user_id     TEXT,
    rating      INTEGER CHECK(rating BETWEEN 1 AND 5),
    comment     TEXT,
    created_at  TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_marketplace_reviews_tool_id ON marketplace_reviews(tool_id);
CREATE INDEX IF NOT EXISTS idx_marketplace_reviews_user_id ON marketplace_reviews(user_id);
"""

_DDL_INVITATION_USES = """
CREATE TABLE IF NOT EXISTS invitation_uses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL,
    inviter_id  TEXT NOT NULL,
    invitee_id  TEXT NOT NULL,
    bonus_given INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (inviter_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (invitee_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_invitation_uses_code ON invitation_uses(code);
CREATE INDEX IF NOT EXISTS idx_invitation_uses_inviter ON invitation_uses(inviter_id);
"""

_DDL_SPARK_SCORES = """
CREATE TABLE IF NOT EXISTS spark_scores (
    tool_name TEXT PRIMARY KEY,
    utility_score REAL,
    industrial_score REAL,
    stability_score REAL,
    speed_score REAL,
    update_score REAL,
    security_score REAL,
    compatibility_score REAL,
    review_score REAL,
    star_score REAL,
    total_score REAL,
    grade TEXT,
    evaluated_at TIMESTAMP DEFAULT (datetime('now','localtime'))
);
"""

_DDL_SPARK_REVIEWS = """
CREATE TABLE IF NOT EXISTS spark_reviews (
    id TEXT PRIMARY KEY,
    tool_name TEXT,
    user_id TEXT,
    rating INTEGER CHECK(rating BETWEEN 1 AND 5),
    comment TEXT,
    thumbs_up INTEGER DEFAULT 0,
    thumbs_down INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_spark_reviews_tool ON spark_reviews(tool_name);
CREATE INDEX IF NOT EXISTS idx_spark_reviews_user ON spark_reviews(user_id);
"""

_DDL_SPARK_STARS = """
CREATE TABLE IF NOT EXISTS spark_stars (
    tool_name TEXT,
    user_id TEXT,
    starred_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (tool_name, user_id)
);
CREATE INDEX IF NOT EXISTS idx_spark_stars_tool ON spark_stars(tool_name);
"""

_DDL_SPARK_REPO_STARS = """
CREATE TABLE IF NOT EXISTS spark_repo_stars (
    tool_name TEXT PRIMARY KEY,
    repo_url TEXT,
    github_stars INTEGER DEFAULT 0,
    last_synced TIMESTAMP
);
"""

_DDL_MEMORY_RELATIONS = """
CREATE TABLE IF NOT EXISTS memory_relations (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    entity          TEXT NOT NULL,
    relation        TEXT NOT NULL,
    target          TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_memory_relations_agent_user ON memory_relations(agent_id, user_id);
CREATE INDEX IF NOT EXISTS idx_memory_relations_entity ON memory_relations(agent_id, user_id, entity);
CREATE INDEX IF NOT EXISTS idx_memory_relations_relation ON memory_relations(agent_id, user_id, relation);
CREATE INDEX IF NOT EXISTS idx_memory_relations_target ON memory_relations(agent_id, user_id, target);
"""

_ALL_DDL = [_DDL_USERS, _DDL_AGENTS, _DDL_SERVICES, _DDL_TRANSACTIONS, _DDL_MESSAGES, _DDL_AUDIT_LOG, _DDL_TASKS,
          _DDL_AUCTIONS, _DDL_BIDS, _DDL_BOOKS, _DDL_USED_GOODS, _DDL_RENTALS, _DDL_STOCKS_PORTFOLIOS, _DDL_STOCK_TRADES,
          _DDL_AGENT_SKILLS, _DDL_ROLES, _DDL_SHOWCASES, _DDL_SKILL_DEFINITIONS, _DDL_SKILL_RATINGS, _DDL_SETTLEMENT_REQUESTS,
          _DDL_INVITATION_CODES, _DDL_INVITATION_USES, _DDL_SESSIONS, _DDL_USER_PROFILES, _DDL_USER_OUTPUTS,
          _DDL_MARKETPLACE_TOOLS, _DDL_MARKETPLACE_REVIEWS,
          _DDL_AGENT_SOULS, _DDL_AGENT_MEMORIES,
          _DDL_AI_MEMORIES, _DDL_AI_CONVERSATIONS,
          _DDL_MEMORY_RELATIONS,
          _DDL_SPARK_SCORES, _DDL_SPARK_REVIEWS, _DDL_SPARK_STARS, _DDL_SPARK_REPO_STARS]


# ═══════════════════════════════════════════════════════════════════
# Database 类
# ═══════════════════════════════════════════════════════════════════

class Database:
    """线程安全的 SQLite 数据库封装。

    使用 threading.Lock 保护写操作，每次调用 conn() 获取独立连接，
    避免跨线程共享连接导致的问题。
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        """初始化数据库实例。

        Args:
            db_path: SQLite 数据库文件路径，默认使用 settings.db_path。
        """
        self._db_path = db_path or settings.db_path
        self._lock = threading.Lock()

    # ── 初始化 ─────────────────────────────────────────────────

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

    # ── 连接上下文管理器 ───────────────────────────────────────

    @contextmanager
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

    # ── 辅助方法 ───────────────────────────────────────────────

    @staticmethod
    def _new_id() -> str:
        """生成 UUID4 主键。"""
        return uuid.uuid4().hex

    @staticmethod
    def _short_id(prefix: str = "") -> str:
        """生成短ID：前缀+12位随机（如 TK3k7m2pRq9xW）。"""
        chars = string.ascii_letters + string.digits
        return prefix + ''.join(random.choices(chars, k=12))

    @staticmethod
    def _generate_id(prefix: str = "ZH") -> str:
        """生成带前缀的14位短ID（2位前缀 + 12位随机字符）。"""
        chars = string.ascii_letters + string.digits  # a-z, A-Z, 0-9
        return prefix + ''.join(random.choices(chars, k=12))

    @staticmethod
    def _row_to_dict(row):
        """将 sqlite3.Row 转换为 dict，None 原样返回。"""
        return dict(row) if row else None

    def _execute_write(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """线程安全地执行写操作。"""
        with self._lock:
            with self.conn() as conn:
                return conn.execute(sql, params)

    # ═════════════════════════════════════════════════════════════
    # users 表 CRUD
    # ═════════════════════════════════════════════════════════════

    def create_user(self, username: str, password_hash: str,
                    balance_cents: float = 0.0, is_admin: int = 0) -> str:
        """创建用户，返回新用户 ID。"""
        uid = self._generate_id("ZH")
        sql = """INSERT INTO users (id, username, password_hash, balance_cents, is_admin)
                 VALUES (?, ?, ?, ?, ?)"""
        self._execute_write(sql, (uid, username, password_hash, balance_cents, is_admin))
        return uid

    def get_user(self, user_id: str):
        """按 ID 查询用户，返回 sqlite3.Row 或 None。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            )

    def get_user_by_username(self, username: str):
        """按用户名查询用户。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            )

    def list_users(self, limit: int = 100, offset: int = 0):
        """分页列出用户。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_user(self, user_id: str, **kwargs) -> bool:
        """按 ID 更新用户字段。返回是否成功。"""
        if not kwargs:
            return False
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE users SET {sets} WHERE id = ?"
        params = tuple(kwargs.values()) + (user_id,)
        self._execute_write(sql, params)
        return True

    def delete_user(self, user_id: str) -> bool:
        """按 ID 删除用户。"""
        self._execute_write("DELETE FROM users WHERE id = ?", (user_id,))
        return True

    # ═════════════════════════════════════════════════════════════
    # user_profiles 表 CRUD
    # ═════════════════════════════════════════════════════════════

    def upsert_user_profile(self, user_id: str, company_name: str = "",
                            industry: str = "", role: str = "",
                            preferences: str = "", notes: str = "") -> bool:
        """创建或更新用户画像。"""
        sql = """INSERT INTO user_profiles (user_id, company_name, industry, role, preferences, notes, updated_at)
                 VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'))
                 ON CONFLICT(user_id) DO UPDATE SET
                     company_name = excluded.company_name,
                     industry = excluded.industry,
                     role = excluded.role,
                     preferences = excluded.preferences,
                     notes = excluded.notes,
                     updated_at = datetime('now','localtime')"""
        self._execute_write(sql, (user_id, company_name, industry, role, preferences, notes))
        return True

    def get_user_profile(self, user_id: str):
        """获取用户画像，不存在则返回空 dict。"""
        with self.conn() as conn:
            row = self._row_to_dict(
                conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
            )
            if row:
                return row
            return {"user_id": user_id, "company_name": "", "industry": "",
                    "role": "", "preferences": "", "notes": ""}

    # ═════════════════════════════════════════════════════════════
    # user_outputs 表 CRUD
    # ═════════════════════════════════════════════════════════════

    def save_user_output(self, user_id: str, agent_id: str,
                         title: str = "", content: str = "") -> str:
        """保存 AI 产出物，返回记录 ID。"""
        oid = self._new_id()
        self._execute_write(
            "INSERT INTO user_outputs (id, user_id, agent_id, title, content) VALUES (?, ?, ?, ?, ?)",
            (oid, user_id, agent_id, title, content)
        )
        return oid

    def list_user_outputs(self, user_id: str, limit: int = 50, offset: int = 0):
        """列出用户的所有产出物，按时间倒序。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM user_outputs WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset)
            ).fetchall()
            return [dict(r) for r in rows]

    # ═════════════════════════════════════════════════════════════════
    # marketplace_tools 表 CRUD — 工具市场
    # ═════════════════════════════════════════════════════════════════

    def create_marketplace_tool(self, name: str, description: str = "",
                                author_id: str = "", category: str = "",
                                mcp_server_code: str = "",
                                config_json: str = "") -> dict:
        """发布工具到市场，返回工具信息字典。"""
        tool_id = self._short_id("MP")
        now = "datetime('now','localtime')"
        from datetime import datetime
        ts = datetime.now().isoformat()
        sql = """INSERT INTO marketplace_tools
                 (id, name, description, author_id, category, stars, downloads,
                  status, mcp_server_code, config_json, created_at, updated_at)
                 VALUES (?, ?, ?, ?, ?, 0, 0, 'pending', ?, ?, ?, ?)"""
        self._execute_write(sql, (tool_id, name, description, author_id, category,
                                  mcp_server_code, config_json, ts, ts))
        return self.get_marketplace_tool(tool_id)

    def get_marketplace_tool(self, tool_id: str):
        """按 ID 查询市场工具。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM marketplace_tools WHERE id = ?", (tool_id,)).fetchone()
            )

    def list_marketplace_tools(self, status: str = "approved", category: str = "",
                                limit: int = 50, offset: int = 0) -> list:
        """列出市场工具，可按状态和分类过滤。"""
        with self.conn() as conn:
            conditions = []
            params = []
            if status:
                conditions.append("status = ?")
                params.append(status)
            if category:
                conditions.append("category = ?")
                params.append(category)
            where = " AND ".join(conditions) if conditions else "1=1"
            rows = conn.execute(
                f"SELECT * FROM marketplace_tools WHERE {where} ORDER BY stars DESC, downloads DESC LIMIT ? OFFSET ?",
                tuple(params) + (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def search_marketplace_tools(self, keyword: str, category: str = "",
                                 sort_by: str = "stars", limit: int = 50) -> list:
        """搜索市场工具，按关键词匹配名称和描述。"""
        with self.conn() as conn:
            conditions = ["status = 'approved'"]
            params = []
            if keyword:
                conditions.append("(name LIKE ? OR description LIKE ?)")
                kw = f"%{keyword}%"
                params.extend([kw, kw])
            if category:
                conditions.append("category = ?")
                params.append(category)
            where = " AND ".join(conditions)
            order = "stars DESC"
            if sort_by == "downloads":
                order = "downloads DESC"
            elif sort_by == "newest":
                order = "created_at DESC"
            rows = conn.execute(
                f"SELECT * FROM marketplace_tools WHERE {where} ORDER BY {order} LIMIT ?",
                tuple(params) + (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_marketplace_tool(self, tool_id: str, **kwargs) -> bool:
        """按 ID 更新市场工具字段。"""
        if not kwargs:
            return False
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE marketplace_tools SET {sets}, updated_at = datetime('now','localtime') WHERE id = ?"
        params = tuple(kwargs.values()) + (tool_id,)
        self._execute_write(sql, params)
        return True

    def increment_tool_downloads(self, tool_id: str) -> None:
        """原子地将工具下载数加 1。"""
        with self._lock:
            with self.conn() as conn:
                conn.execute(
                    "UPDATE marketplace_tools SET downloads = downloads + 1 WHERE id = ?",
                    (tool_id,),
                )

    # ═════════════════════════════════════════════════════════════════
    # marketplace_reviews 表 CRUD — 工具评价
    # ═════════════════════════════════════════════════════════════════

    def create_marketplace_review(self, tool_id: str, user_id: str,
                                  rating: int, comment: str = "") -> dict:
        """给工具添加评价，同时更新工具的 stars 均值。返回评价信息。"""
        if rating < 1 or rating > 5:
            raise ValueError("评分必须在 1-5 之间")
        review_id = self._short_id("RV")
        from datetime import datetime
        ts = datetime.now().isoformat()
        sql = """INSERT INTO marketplace_reviews (id, tool_id, user_id, rating, comment, created_at)
                 VALUES (?, ?, ?, ?, ?, ?)"""
        self._execute_write(sql, (review_id, tool_id, user_id, rating, comment, ts))
        # 重新计算该工具的平均评分
        with self.conn() as conn:
            row = conn.execute(
                "SELECT AVG(rating) as avg_rating, COUNT(*) as count FROM marketplace_reviews WHERE tool_id = ?",
                (tool_id,),
            ).fetchone()
            avg_rating = round(row["avg_rating"]) if row and row["avg_rating"] else 0
            conn.execute(
                "UPDATE marketplace_tools SET stars = ? WHERE id = ?",
                (avg_rating, tool_id),
            )
        return self.get_marketplace_review(review_id)

    def get_marketplace_review(self, review_id: str):
        """按 ID 查询评价。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM marketplace_reviews WHERE id = ?", (review_id,)).fetchone()
            )

    def list_marketplace_reviews(self, tool_id: str, limit: int = 50) -> list:
        """列出某工具的评分记录。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM marketplace_reviews WHERE tool_id = ? ORDER BY created_at DESC LIMIT ?",
                (tool_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_tool_rating_summary(self, tool_id: str) -> dict:
        """获取工具评分汇总。"""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT AVG(rating) as avg_rating, COUNT(*) as count FROM marketplace_reviews WHERE tool_id = ?",
                (tool_id,),
            ).fetchone()
            return {
                "avg_rating": round(row["avg_rating"], 1) if row and row["avg_rating"] else 0.0,
                "count": row["count"] if row else 0,
            }

    # ── 等级体系辅助方法 ──────────────────────────────────────

    def get_user_recharge_total(self, user_id: str) -> float:
        """获取用户累计充值总额（积分）"""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(amount_cents), 0) FROM transactions WHERE to_id = ? AND type = 'recharge'",
                (user_id,)
            ).fetchone()
        return row[0] if row else 0.0

    def get_user_earned_total(self, user_id: str) -> float:
        """获取用户赚取总额（当前余额）"""
        with self.conn() as conn:
            row = conn.execute("SELECT COALESCE(balance_cents, 0) FROM users WHERE id = ?", (user_id,)).fetchone()
        return row[0] if row else 0.0

    def get_dev_sales_total(self, user_id: str) -> float:
        """获取开发者通过平台销售技能的总收入（累计）"""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(amount_cents), 0) FROM transactions WHERE to_id = ? AND type = 'payment' AND description LIKE '购买开发者技能:%'",
                (user_id,)
            ).fetchone()
        return row[0] if row else 0.0

    def count_user_agents(self, user_id: str) -> int:
        """获取用户拥有的非系统Agent数量"""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM agents WHERE user_id = ? AND is_system = 0",
                (user_id,)
            ).fetchone()
        return row[0] if row else 0

    # ── 余额原子操作 ───────────────────────────────────────────

    def adjust_balance(self, entity_id: str, delta: float,
                       entity_type: str = "user") -> float:
        """原子地调整余额（delta 可为正/负），返回调整后的余额。

        Args:
            entity_id: 用户或 Agent ID。
            delta: 余额变动量（正数为充值，负数为扣费）。
            entity_type: 'user' 或 'agent'。

        使用 SELECT ... FOR UPDATE 风格：在同一事务内先锁定读取再更新，
        SQLite 通过串行写锁保证原子性。
        """
        if entity_type not in ("user", "agent"):
            raise ValueError(f"不支持的实体类型: {entity_type}")
        table = "users" if entity_type == "user" else "agents"
        label = "用户" if entity_type == "user" else "Agent"
        with self._lock:
            with self.conn() as conn:
                row = conn.execute(
                    f"SELECT balance_cents FROM {table} WHERE id = ?",
                    (entity_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"{label}不存在: {entity_id}")
                new_balance = row["balance_cents"] + delta
                if new_balance < 0:
                    raise ValueError(
                        f"{label}余额不足: 当前 {row['balance_cents']:.2f} 积分，需要 {abs(delta):.2f} 积分"
                    )
                conn.execute(
                    f"UPDATE {table} SET balance_cents = ? WHERE id = ?",
                    (new_balance, entity_id),
                )
                return new_balance

    # ═════════════════════════════════════════════════════════════
    # agents 表 CRUD
    # ═════════════════════════════════════════════════════════════

    def create_agent(self, user_id: str, name: str, system_prompt: str = "",
                     tier: str = "一级", status: str = "running",
                     balance_cents: float | None = None,
                     is_system: int = 0,
                     api_provider: str = "",
                     api_key: str = "",
                     api_model: str = "") -> str:
        """创建 Agent，返回新 Agent ID。"""
        aid = self._generate_id("AI")
        balance_cents = balance_cents if balance_cents is not None else settings.starting_credits
        sql = """INSERT INTO agents (id, user_id, name, system_prompt, tier, status, balance_cents, is_system, api_provider, api_key, api_model)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        self._execute_write(sql, (aid, user_id, name, system_prompt, tier, status, balance_cents, is_system, api_provider, api_key, api_model))
        return aid

    def create_system_agent(self, st_id: str, user_id: str, name: str,
                            system_prompt: str = "",
                            balance_cents: float = 1000.0) -> str:
        """创建系统内置管理 Agent，使用 ST 前缀 ID。

        Args:
            st_id: 系统 Agent ID（如 'ST01', 'ST02' 等）。
            user_id: 关联的用户 ID。
            name: Agent 名称。
            system_prompt: 系统提示词/职责描述。
            balance_cents: 初始积分余额（默认 1000）。

        Returns:
            创建的 Agent ID。
        """
        sql = """INSERT OR IGNORE INTO agents
                 (id, user_id, name, system_prompt, tier, status, balance_cents, is_system)
                 VALUES (?, ?, ?, ?, 'admin', 'paused', ?, 1)"""
        self._execute_write(sql, (st_id, user_id, name, system_prompt, balance_cents))
        return st_id

    def get_agent(self, agent_id: str):
        """按 ID 查询 Agent。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            )

    def list_agents_by_user(self, user_id: str):
        """列出某用户的所有 Agent。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM agents WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_agents(self, limit: int = 100, offset: int = 0):
        """分页列出所有 Agent。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM agents ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_agents_for_sale(self):
        """列出所有待售的 AI 智能体（for_sale_price 不为空）。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT a.*, u.username as owner_name FROM agents a LEFT JOIN users u ON a.user_id=u.id WHERE a.for_sale_price IS NOT NULL AND a.is_system=0 ORDER BY a.for_sale_price ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def list_agents_for_rent(self):
        """列出所有可租的 AI 智能体（for_rent_price 不为空）。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT a.*, u.username as owner_name FROM agents a LEFT JOIN users u ON a.user_id=u.id WHERE a.for_rent_price IS NOT NULL AND a.is_system=0 ORDER BY a.for_rent_price ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def update_agent(self, agent_id: str, **kwargs) -> bool:
        """按 ID 更新 Agent 字段。"""
        if not kwargs:
            return False
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = "datetime('now','localtime')"
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE agents SET {sets} WHERE id = ?"
        params = tuple(kwargs.values()) + (agent_id,)
        self._execute_write(sql, params)
        return True

    def delete_agent(self, agent_id: str) -> bool:
        """按 ID 删除 Agent。"""
        self._execute_write("DELETE FROM agents WHERE id = ?", (agent_id,))
        return True

    # ═════════════════════════════════════════════════════════════
    # services 表 CRUD
    # ═════════════════════════════════════════════════════════════

    def create_service(self, agent_id: str, name: str, description: str = "",
                       price_cents: float = 0.0) -> str:
        """创建服务，返回新服务 ID。"""
        sid = self._short_id("FW")
        sql = """INSERT INTO services (id, agent_id, name, description, price_cents)
                 VALUES (?, ?, ?, ?, ?)"""
        self._execute_write(sql, (sid, agent_id, name, description, price_cents))
        return sid

    def get_service(self, service_id: str):
        """按 ID 查询服务。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute(
                    "SELECT * FROM services WHERE id = ?", (service_id,)
                ).fetchone()
            )

    def get_service_by_agent(self, agent_id: str):
        """按所属 Agent ID 查询服务列表。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM services WHERE agent_id = ? ORDER BY created_at DESC",
                (agent_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_services(self, status: Optional[str] = None,
                      limit: int = 100, offset: int = 0):
        """列出服务，可按状态过滤。"""
        with self.conn() as conn:
            conditions = []
            params = []
            if status:
                conditions.append("status = ?")
                params.append(status)
            where = " AND ".join(conditions) if conditions else "1=1"
            rows = conn.execute(
                f"SELECT * FROM services WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                tuple(params) + (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_service(self, service_id: str, **kwargs) -> bool:
        """按 ID 更新服务字段。"""
        if not kwargs:
            return False
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE services SET {sets} WHERE id = ?"
        params = tuple(kwargs.values()) + (service_id,)
        self._execute_write(sql, params)
        return True

    def delete_service(self, service_id: str) -> bool:
        """按 ID 删除服务。"""
        self._execute_write("DELETE FROM services WHERE id = ?", (service_id,))
        return True

    # ═════════════════════════════════════════════════════════════
    # transactions 表 CRUD
    # ═════════════════════════════════════════════════════════════

    def create_transaction(self, from_id: Optional[str], to_id: Optional[str],
                           amount_cents: float, tx_type: str,
                           description: str = "") -> str:
        """创建交易记录，返回交易 ID。"""
        tid = self._short_id("JY")
        sql = """INSERT INTO transactions (id, from_id, to_id, amount_cents, type, description)
                 VALUES (?, ?, ?, ?, ?, ?)"""
        self._execute_write(
            sql, (tid, from_id, to_id, amount_cents, tx_type, description)
        )
        return tid

    def get_transaction(self, tx_id: str):
        """按 ID 查询交易。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute(
                    "SELECT * FROM transactions WHERE id = ?", (tx_id,)
                ).fetchone()
            )

    def list_transactions_by_user(self, user_id: str, limit: int = 100, offset: int = 0):
        """列出某用户及其所有 Agent 相关的交易记录（按时间倒序）。"""
        with self.conn() as conn:
            agent_rows = conn.execute(
                "SELECT id FROM agents WHERE user_id = ?", (user_id,)
            ).fetchall()
            entity_ids = [user_id] + [r["id"] for r in agent_rows]
            if not entity_ids:
                return []
            placeholders = ",".join("?" * len(entity_ids))
            rows = conn.execute(
                f"SELECT * FROM transactions WHERE from_id IN ({placeholders}) OR to_id IN ({placeholders}) ORDER BY created_at DESC LIMIT ? OFFSET ?",
                entity_ids + entity_ids + [limit, offset],
            ).fetchall()
            return [dict(r) for r in rows]

    def list_transactions_by_entity(self, entity_id: str, limit: int = 100, offset: int = 0):
        """列出某实体（用户/Agent）相关的交易记录（按时间倒序）。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE from_id = ? OR to_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (entity_id, entity_id, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_transactions(self, limit: int = 100, offset: int = 0):
        """分页列出所有交易。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM transactions ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    # ═════════════════════════════════════════════════════════════
    # messages 表 CRUD
    # ═════════════════════════════════════════════════════════════

    def create_message(self, agent_id: str, role: str, content: str = "",
                       turn_seq: int = 0) -> int:
        """创建消息记录，返回消息 ID（自增）。"""
        sql = """INSERT INTO messages (agent_id, role, content, turn_seq)
                 VALUES (?, ?, ?, ?)"""
        cursor = self._execute_write(sql, (agent_id, role, content, turn_seq))
        return cursor.lastrowid

    def get_message(self, msg_id):
        """按 ID 查询消息。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute(
                    "SELECT * FROM messages WHERE id = ?", (msg_id,)
                ).fetchone()
            )

    def list_messages_by_agent(self, agent_id: str, limit: int = 100, offset: int = 0):
        """列出某 Agent 对话的消息（按时间倒序）。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE agent_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (agent_id, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_message(self, msg_id: int) -> bool:
        """按 ID 删除消息。"""
        self._execute_write("DELETE FROM messages WHERE id = ?", (int(msg_id),))
        return True

    # ═════════════════════════════════════════════════════════════
    # audit_log 表 CRUD
    # ═════════════════════════════════════════════════════════════

    def create_audit_log(self, agent_id: str, action: str, detail: str = "") -> int:
        """创建审计日志，返回日志 ID（自增）。"""
        sql = """INSERT INTO audit_log (agent_id, action, detail)
                 VALUES (?, ?, ?)"""
        cursor = self._execute_write(sql, (agent_id, action, detail))
        return cursor.lastrowid

    def get_audit_log(self, log_id):
        """按 ID 查询审计日志。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute(
                    "SELECT * FROM audit_log WHERE id = ?", (log_id,)
                ).fetchone()
            )

    def list_audit_logs_by_agent(self, agent_id: str, limit: int = 100, offset: int = 0):
        """列出某 Agent 的审计日志（按时间倒序）。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE agent_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (agent_id, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_audit_logs(self, limit: int = 100, offset: int = 0):
        """分页列出所有审计日志。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    # ═════════════════════════════════════════════════════════════
    # tasks 表 CRUD — 任务市场
    # ═════════════════════════════════════════════════════════════

    def create_task(self, title: str, description: str = "",
                    reward: float = 0.0, creator_id: str = "") -> dict:
        """创建任务，返回任务信息字典。"""
        task_id = self._short_id("RW")
        sql = """INSERT INTO tasks (id, title, description, reward, creator_id)
                 VALUES (?, ?, ?, ?, ?)"""
        self._execute_write(sql, (task_id, title, description, reward, creator_id))
        return self.get_task(task_id)

    def get_task(self, task_id: str):
        """按 ID 查询任务。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            )

    def list_tasks(self, status: Optional[str] = None):
        """列出任务，可按状态过滤 (OPEN/CLAIMED/COMPLETED/CANCELLED)。"""
        with self.conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def claim_task(self, task_id: str, agent_id: str) -> dict:
        """接单：将 OPEN 状态任务设为 CLAIMED，设置接单 Agent。

        Returns:
            更新后的任务字典。

        Raises:
            ValueError: 任务不存在或状态不是 OPEN。
        """
        with self._lock:
            with self.conn() as conn:
                task = conn.execute(
                    "SELECT * FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
                if task is None:
                    raise ValueError(f"任务不存在: {task_id}")
                if task["status"] != "OPEN":
                    raise ValueError(
                        f"任务状态不是 OPEN，无法接单: {task['status']}"
                    )
                conn.execute(
                    """UPDATE tasks SET status = 'CLAIMED', assignee_id = ?,
                       updated_at = datetime('now','localtime') WHERE id = ?""",
                    (agent_id, task_id),
                )
                return self._row_to_dict(
                    conn.execute(
                        "SELECT * FROM tasks WHERE id = ?", (task_id,)
                    ).fetchone()
                )

    def complete_task(self, task_id: str) -> dict:
        """完成任务：将 CLAIMED 状态任务设为 COMPLETED。

        Returns:
            更新前的任务字典（含 assignee_id 等信息）。

        Raises:
            ValueError: 任务不存在或状态不是 CLAIMED。
        """
        with self._lock:
            with self.conn() as conn:
                task = conn.execute(
                    "SELECT * FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
                if task is None:
                    raise ValueError(f"任务不存在: {task_id}")
                if task["status"] != "CLAIMED":
                    raise ValueError(
                        f"任务状态不是 CLAIMED，无法完成: {task['status']}"
                    )
                task_dict = dict(task)
                conn.execute(
                    """UPDATE tasks SET status = 'COMPLETED',
                       updated_at = datetime('now','localtime') WHERE id = ?""",
                    (task_id,),
                )
                return task_dict

    def cancel_task(self, task_id: str) -> dict:
        """取消任务：将任务状态设为 CANCELLED。

        Returns:
            更新前的任务字典。

        Raises:
            ValueError: 任务不存在。
        """
        with self._lock:
            with self.conn() as conn:
                task = conn.execute(
                    "SELECT * FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
                if task is None:
                    raise ValueError(f"任务不存在: {task_id}")
                task_dict = dict(task)
                conn.execute(
                    """UPDATE tasks SET status = 'CANCELLED',
                       updated_at = datetime('now','localtime') WHERE id = ?""",
                    (task_id,),
                )
                return task_dict

    # ═════════════════════════════════════════════════════════════════
    # books 表 CRUD — 百科市场
    # ═════════════════════════════════════════════════════════════════

    def create_book(self, author_id: str, title: str,
                    description: str = "", content: str = "",
                    price: float = 0.0) -> dict:
        """创建图书（DRAFT 状态），返回图书信息字典。"""
        book_id = self._short_id("TS")
        sql = """INSERT INTO books (id, author_id, title, description, content, price)
                 VALUES (?, ?, ?, ?, ?, ?)"""
        self._execute_write(sql, (book_id, author_id, title, description, content, price))
        return self.get_book(book_id)

    def get_book(self, book_id: str):
        """按 ID 查询图书。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
            )

    def list_books(self, author_id: Optional[str] = None):
        """列出所有 PUBLISHED 状态的图书，可按 author_id 过滤。不返回 content 字段。"""
        with self.conn() as conn:
            if author_id:
                rows = conn.execute(
                    "SELECT * FROM books WHERE status = 'PUBLISHED' AND author_id = ? ORDER BY created_at DESC",
                    (author_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM books WHERE status = 'PUBLISHED' ORDER BY created_at DESC"
                ).fetchall()
            books = [dict(r) for r in rows]
            # 列表浏览时不返回正文内容
            for b in books:
                b.pop("content", None)
            return books

    def publish_book(self, book_id: str) -> dict:
        """将图书状态设为 PUBLISHED。

        Returns:
            更新后的图书字典。

        Raises:
            ValueError: 图书不存在。
        """
        with self._lock:
            with self.conn() as conn:
                book = conn.execute(
                    "SELECT * FROM books WHERE id = ?", (book_id,)
                ).fetchone()
                if book is None:
                    raise ValueError(f"图书不存在: {book_id}")
                conn.execute(
                    "UPDATE books SET status = 'PUBLISHED' WHERE id = ?",
                    (book_id,),
                )
                return self._row_to_dict(
                    conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
                )

    def increment_download_count(self, book_id: str) -> None:
        """原子地将图书 download_count 加 1。"""
        with self._lock:
            with self.conn() as conn:
                conn.execute(
                    "UPDATE books SET download_count = download_count + 1 WHERE id = ?",
                    (book_id,),
                )

    # ═════════════════════════════════════════════════════════════
    # auctions 表 CRUD — 拍卖市场
    # ═════════════════════════════════════════════════════════════

    def create_auction(self, seller_id: str, title: str,
                       description: str = "", starting_price: float = 0.0,
                       duration_hours: int = 24) -> dict:
        """创建拍卖，返回拍卖信息字典。"""
        auction_id = self._short_id("PM")
        sql = """INSERT INTO auctions (id, seller_id, title, description,
                 starting_price, current_bid, status, ended_at)
                 VALUES (?, ?, ?, ?, ?, 0, 'ACTIVE',
                         datetime('now', ? || ' hours'))"""
        self._execute_write(
            sql, (auction_id, seller_id, title, description,
                  starting_price, str(duration_hours))
        )
        return self.get_auction(auction_id)

    def get_auction(self, auction_id: str) -> dict:
        """按 ID 查询拍卖（含当前出价列表）。"""
        with self.conn() as conn:
            auction = self._row_to_dict(
                conn.execute(
                    "SELECT * FROM auctions WHERE id = ?", (auction_id,)
                ).fetchone()
            )
            if auction is None:
                return None
            # 加载关联的出价记录
            bids = conn.execute(
                "SELECT * FROM bids WHERE auction_id = ? ORDER BY created_at ASC",
                (auction_id,),
            ).fetchall()
            auction["bids"] = [dict(b) for b in bids]
            return auction

    def list_auctions(self, status: Optional[str] = None) -> list:
        """列出拍卖，可按 status 过滤 (ACTIVE/SETTLED/CANCELLED)。"""
        with self.conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM auctions WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM auctions ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def place_bid(self, auction_id: str, bidder_id: str, amount: float) -> dict:
        """竞拍出价。

        流程：
          1. 检查拍卖存在且状态为 ACTIVE。
          2. 验证 amount > starting_price 且 amount > 当前最高价。
          3. 验证 bidder 余额充足。
          4. 从 bidder 扣除竞价金额（冻结）。
          5. 写入 bids 表。
          6. 更新 auctions.current_bid 和 winner_id。
          7. 如果之前有最高出价人，退回其冻结金额。
          8. 返回更新后的拍卖信息。

        Raises:
            ValueError: 任何校验或业务规则失败时抛出。
        """
        with self._lock:
            with self.conn() as conn:
                # 1. 获取拍卖
                auction = conn.execute(
                    "SELECT * FROM auctions WHERE id = ?", (auction_id,)
                ).fetchone()
                if auction is None:
                    raise ValueError(f"拍卖不存在: {auction_id}")
                if auction["status"] != "ACTIVE":
                    raise ValueError(
                        f"拍卖状态不是 ACTIVE，无法出价: {auction['status']}"
                    )

                # 2. 验证出价金额
                if amount <= auction["starting_price"]:
                    raise ValueError(
                        f"出价金额 {amount:.2f} 必须高于起拍价 {auction['starting_price']:.2f}"
                    )
                if amount <= auction["current_bid"]:
                    raise ValueError(
                        f"出价金额 {amount:.2f} 必须高于当前最高价 {auction['current_bid']:.2f}"
                    )

                # 3. 验证 bidder 存在且余额充足
                bidder = conn.execute(
                    "SELECT * FROM agents WHERE id = ?", (bidder_id,)
                ).fetchone()
                if bidder is None:
                    raise ValueError(f"竞拍者 Agent 不存在: {bidder_id}")
                if bidder["balance_cents"] < amount:
                    raise ValueError(
                        f"竞拍者余额不足: 当前 {bidder['balance_cents']:.2f}，"
                        f"需要 {amount:.2f}"
                    )

                previous_winner_id = auction["winner_id"]
                previous_bid = auction["current_bid"]

                # 4. 从 bidder 扣款（冻结）
                conn.execute(
                    "UPDATE agents SET balance_cents = balance_cents - ? WHERE id = ?",
                    (amount, bidder_id),
                )

                # 5. 记录出价
                conn.execute(
                    "INSERT INTO bids (auction_id, bidder_id, amount) VALUES (?, ?, ?)",
                    (auction_id, bidder_id, amount),
                )

                # 6. 更新拍卖当前出价和赢家
                conn.execute(
                    "UPDATE auctions SET current_bid = ?, winner_id = ? WHERE id = ?",
                    (amount, bidder_id, auction_id),
                )

                # 7. 如果有之前最高出价人，退回冻结金额
                if previous_winner_id and previous_winner_id != bidder_id and previous_bid > 0:
                    conn.execute(
                        "UPDATE agents SET balance_cents = balance_cents + ? WHERE id = ?",
                        (previous_bid, previous_winner_id),
                    )
                    conn.execute(
                        "INSERT INTO transactions (id, from_id, to_id, amount_cents, type, description) "
                        "VALUES (?, NULL, ?, ?, 'refund', ?)",
                        (self._new_id(), previous_winner_id, previous_bid,
                         f"auction_outbid_refund:{auction_id}"),
                    )

                # 记录冻结交易
                conn.execute(
                    "INSERT INTO transactions (id, from_id, to_id, amount_cents, type, description) "
                    "VALUES (?, ?, NULL, ?, 'payment', ?)",
                    (self._new_id(), bidder_id, amount,
                     f"auction_bid_freeze:{auction_id}"),
                )

                return self._row_to_dict(
                    conn.execute(
                        "SELECT * FROM auctions WHERE id = ?", (auction_id,)
                    ).fetchone()
                )

    def settle_auction(self, auction_id: str, seller_id: str) -> dict:
        """结算拍卖。

        流程：
          1. 检查拍卖存在且状态为 ACTIVE。
          2. 检查请求者是 seller。
          3. 如果有 winner，将 current_bid 从冻结状态转给 seller。
          4. 将拍卖状态改为 SETTLED。
          5. 返回更新后的拍卖信息。

        Raises:
            ValueError: 任何校验或业务规则失败时抛出。
        """
        with self._lock:
            with self.conn() as conn:
                auction = conn.execute(
                    "SELECT * FROM auctions WHERE id = ?", (auction_id,)
                ).fetchone()
                if auction is None:
                    raise ValueError(f"拍卖不存在: {auction_id}")
                if auction["status"] != "ACTIVE":
                    raise ValueError(
                        f"拍卖状态不是 ACTIVE，无法结算: {auction['status']}"
                    )
                if auction["seller_id"] != seller_id:
                    raise ValueError(
                        f"只有卖家可以结算拍卖 (seller={auction['seller_id']})"
                    )

                winner_id = auction["winner_id"]
                current_bid = auction["current_bid"]

                if winner_id and current_bid > 0:
                    # 将竞价金转给卖家
                    conn.execute(
                        "UPDATE agents SET balance_cents = balance_cents + ? WHERE id = ?",
                        (current_bid, seller_id),
                    )
                    conn.execute(
                        "INSERT INTO transactions (id, from_id, to_id, amount_cents, type, description) "
                        "VALUES (?, ?, ?, ?, 'payment', ?)",
                        (self._new_id(), winner_id, seller_id, current_bid,
                         f"auction_settle:{auction_id}"),
                    )

                # 更新状态
                conn.execute(
                    "UPDATE auctions SET status = 'SETTLED' WHERE id = ?",
                    (auction_id,),
                )

                return self._row_to_dict(
                    conn.execute(
                        "SELECT * FROM auctions WHERE id = ?", (auction_id,)
                    ).fetchone()
                )


# ═══════════════════════════════════════════════════════════════════
# 全局单例

    def create_used_good(self, seller_id: str, name: str,
                         description: str = "", category: str = "tool",
                         price: float = 0.0,
                         original_value: float = 0.0) -> dict:
        """创建旧货商品（ONSALE 状态），返回商品信息字典。"""
        good_id = self._short_id("JH")
        sql = """INSERT INTO used_goods (id, seller_id, name, description, category, price, original_value)
                 VALUES (?, ?, ?, ?, ?, ?, ?)"""
        self._execute_write(sql, (good_id, seller_id, name, description, category, price, original_value))
        return self.get_used_good(good_id)

    def get_used_good(self, good_id: str):
        """按 ID 查询旧货商品。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM used_goods WHERE id = ?", (good_id,)).fetchone()
            )

    def list_used_goods(self, category: Optional[str] = None):
        """列出旧货商品，可按 category 过滤。"""
        with self.conn() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM used_goods WHERE status = 'ONSALE' AND category = ? ORDER BY created_at DESC",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM used_goods WHERE status = 'ONSALE' ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def update_used_good(self, good_id: str, **kwargs) -> bool:
        """按 ID 更新旧货商品字段。"""
        if not kwargs:
            return False
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE used_goods SET {sets} WHERE id = ?"
        params = tuple(kwargs.values()) + (good_id,)
        self._execute_write(sql, params)
        return True

    # ═════════════════════════════════════════════════════════════════
    # rentals 表 CRUD — 租赁市场
    # ═════════════════════════════════════════════════════════════════

    def create_rental(self, owner_id: str, name: str,
                      description: str = "", price_per_hour: float = 0.0,
                      max_duration_hours: int = 24) -> dict:
        """创建租赁物品（AVAILABLE 状态），返回租赁信息字典。"""
        rental_id = self._short_id("ZL")
        sql = """INSERT INTO rentals (id, owner_id, name, description, price_per_hour, max_duration_hours)
                 VALUES (?, ?, ?, ?, ?, ?)"""
        self._execute_write(sql, (rental_id, owner_id, name, description, price_per_hour, max_duration_hours))
        return self.get_rental(rental_id)

    def get_rental(self, rental_id: str):
        """按 ID 查询租赁物品。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM rentals WHERE id = ?", (rental_id,)).fetchone()
            )

    def list_rentals(self, status: Optional[str] = None):
        """列出租赁物品，可按 status 过滤。"""
        with self.conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM rentals WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM rentals ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def update_rental(self, rental_id: str, **kwargs) -> bool:
        """按 ID 更新租赁物品字段。"""
        if not kwargs:
            return False
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE rentals SET {sets} WHERE id = ?"
        params = tuple(kwargs.values()) + (rental_id,)
        self._execute_write(sql, params)
        return True

    # ═════════════════════════════════════════════════════════════════
    # stocks_portfolios 表 CRUD — 模拟股票持仓
    # ═════════════════════════════════════════════════════════════════

    def get_stock_portfolio(self, agent_id: str, symbol: str):
        """查询 Agent 对某只股票的持仓信息。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute(
                    "SELECT * FROM stocks_portfolios WHERE agent_id = ? AND symbol = ?",
                    (agent_id, symbol),
                ).fetchone()
            )

    def list_stock_portfolios(self, agent_id: str) -> list:
        """列出 Agent 所有股票的持仓。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM stocks_portfolios WHERE agent_id = ? ORDER BY symbol",
                (agent_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_stock_portfolio(self, agent_id: str, symbol: str,
                               delta_shares: float, price: float) -> dict:
        """增持或减持股票持仓，原子操作。

        Args:
            agent_id:      Agent ID。
            symbol:        股票代码。
            delta_shares:  股数变动（正=买入，负=卖出）。
            price:         本次成交价。

        Returns:
            更新后的持仓字典。

        Raises:
            ValueError: 减持时持仓不足。
        """
        with self._lock:
            with self.conn() as conn:
                portfolio = conn.execute(
                    "SELECT * FROM stocks_portfolios WHERE agent_id = ? AND symbol = ?",
                    (agent_id, symbol),
                ).fetchone()

                if portfolio is None:
                    # 首次买入：创建新持仓
                    if delta_shares <= 0:
                        raise ValueError("持仓不存在，无法卖出")
                    pid = self._new_id()
                    conn.execute(
                        "INSERT INTO stocks_portfolios (id, agent_id, symbol, shares, avg_cost) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (pid, agent_id, symbol, delta_shares, price),
                    )
                else:
                    pid = portfolio["id"]
                    old_shares = portfolio["shares"]
                    old_avg_cost = portfolio["avg_cost"]
                    new_shares = old_shares + delta_shares

                    if new_shares < 0:
                        raise ValueError(
                            f"持仓不足: 当前 {old_shares:.2f} 股，需卖出 {abs(delta_shares):.2f} 股"
                        )

                    if new_shares == 0:
                        # 清仓
                        conn.execute(
                            "DELETE FROM stocks_portfolios WHERE id = ?", (pid,)
                        )
                        return {
                            "agent_id": agent_id,
                            "symbol": symbol,
                            "shares": 0,
                            "avg_cost": 0,
                        }

                    # 计算新的平均成本（仅在买入时更新 avg_cost）
                    if delta_shares > 0:
                        new_avg_cost = (old_shares * old_avg_cost + delta_shares * price) / new_shares
                    else:
                        new_avg_cost = old_avg_cost

                    conn.execute(
                        "UPDATE stocks_portfolios SET shares = ?, avg_cost = ? WHERE id = ?",
                        (new_shares, round(new_avg_cost, 4), pid),
                    )

                return self._row_to_dict(
                    conn.execute(
                        "SELECT * FROM stocks_portfolios WHERE id = ?", (pid,)
                    ).fetchone()
                )

    # ═════════════════════════════════════════════════════════════════
    # stock_trades 表 CRUD — 模拟股票交易记录
    # ═════════════════════════════════════════════════════════════════

    def create_stock_trade(self, agent_id: str, symbol: str,
                           shares: float, price: float,
                           total_cost: float) -> str:
        """记录一笔股票交易，返回交易 ID。

        Args:
            agent_id:   Agent ID。
            symbol:     股票代码。
            shares:     股数（正=买入，负=卖出）。
            price:      成交价。
            total_cost: 总成交金额（正=支出，负=收入）。
        """
        tid = self._short_id("GP")
        sql = """INSERT INTO stock_trades (id, agent_id, symbol, shares, price, total_cost)
                 VALUES (?, ?, ?, ?, ?, ?)"""
        self._execute_write(sql, (tid, agent_id, symbol, shares, price, total_cost))
        return tid

    def list_stock_trades(self, agent_id: Optional[str] = None,
                          symbol: Optional[str] = None,
                          limit: int = 50) -> list:
        """列出股票交易记录。"""
        conditions = []
        params = []
        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        where = " AND ".join(conditions) if conditions else "1=1"
        with self.conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM stock_trades WHERE {where} ORDER BY created_at DESC LIMIT ?",
                tuple(params) + (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ═════════════════════════════════════════════════════════════════
    # agent_skills 表 CRUD — 技能经济系统
    # ═════════════════════════════════════════════════════════════════

    def create_agent_skill(self, agent_id: str, skill_id: str,
                           source: str = "gift",
                           is_equipped: int = 1) -> str:
        """为Agent添加一个技能，返回记录ID。"""
        sid = self._new_id()
        sql = """INSERT INTO agent_skills (id, agent_id, skill_id, source, is_equipped)
                 VALUES (?, ?, ?, ?, ?)"""
        self._execute_write(sql, (sid, agent_id, skill_id, source, is_equipped))
        return sid

    def get_agent_skills(self, agent_id: str,
                         equipped_only: bool = False) -> list[dict]:
        """获取Agent拥有的技能列表。

        Args:
            agent_id: Agent ID。
            equipped_only: 如果为True，只返回已装备的技能。

        Returns:
            技能记录字典列表（含技能详情，从registry获取）。
        """
        from core.skills.registry import SKILLS
        with self.conn() as conn:
            if equipped_only:
                rows = conn.execute(
                    "SELECT * FROM agent_skills WHERE agent_id = ? AND is_equipped = 1 ORDER BY acquired_at DESC",
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_skills WHERE agent_id = ? ORDER BY acquired_at DESC",
                    (agent_id,),
                ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                # 附加技能详情
                skill_info = SKILLS.get(d["skill_id"])
                if skill_info:
                    d["skill_name"] = skill_info["name"]
                    d["star_level"] = skill_info["star_level"]
                    d["category"] = skill_info["category"]
                    d["description"] = skill_info["description"]
                results.append(d)
            return results

    def get_agent_skill_ids(self, agent_id: str,
                            equipped_only: bool = False) -> list[str]:
        """获取Agent拥有的技能ID列表。"""
        with self.conn() as conn:
            if equipped_only:
                rows = conn.execute(
                    "SELECT skill_id FROM agent_skills WHERE agent_id = ? AND is_equipped = 1",
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT skill_id FROM agent_skills WHERE agent_id = ?",
                    (agent_id,),
                ).fetchall()
            return [r["skill_id"] for r in rows]

    def delete_agent_skill(self, agent_id: str, skill_id: str) -> bool:
        """删除Agent的某个技能记录。"""
        self._execute_write(
            "DELETE FROM agent_skills WHERE agent_id = ? AND skill_id = ?",
            (agent_id, skill_id),
        )
        return True

    def update_agent_skill_equipped(self, agent_id: str, skill_id: str,
                                    is_equipped: int) -> bool:
        """更新Agent技能的装备状态。"""
        self._execute_write(
            "UPDATE agent_skills SET is_equipped = ? WHERE agent_id = ? AND skill_id = ?",
            (is_equipped, agent_id, skill_id),
        )
        return True

    def has_agent_skill(self, agent_id: str, skill_id: str) -> bool:
        """检查Agent是否拥有某个技能。"""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM agent_skills WHERE agent_id = ? AND skill_id = ?",
                (agent_id, skill_id),
            ).fetchone()
            return row is not None

    def count_agent_skills(self, agent_id: str) -> int:
        """统计Agent拥有的技能数量。"""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM agent_skills WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            return row["cnt"] if row else 0

    def list_agents_by_skill(self, skill_id: str) -> list[str]:
        """列出拥有指定技能的所有Agent ID。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT agent_id FROM agent_skills WHERE skill_id = ?",
                (skill_id,),
            ).fetchall()
            return [r["agent_id"] for r in rows]


    # ═════════════════════════════════════════════════════════════
    # showcases 表 CRUD — 星光市场
    # ═════════════════════════════════════════════════════════════

    def create_showcase(self, user_id: str, agent_id: str, title: str,
                        content: str = "") -> dict:
        """发布作品，返回作品信息字典。"""
        showcase_id = self._generate_id("SC")
        sql = """INSERT INTO showcases (id, user_id, agent_id, title, content)
                 VALUES (?, ?, ?, ?, ?)"""
        self._execute_write(sql, (showcase_id, user_id, agent_id, title, content))
        return self.get_showcase(showcase_id)

    def get_showcase(self, showcase_id: str):
        """按 ID 查询作品。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute(
                    "SELECT * FROM showcases WHERE id = ?", (showcase_id,)
                ).fetchone()
            )

    def list_showcases(self, limit: int = 50, offset: int = 0):
        """分页列出所有作品（按时间倒序）。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT s.*, a.name as agent_name
                   FROM showcases s
                   LEFT JOIN agents a ON s.agent_id = a.id
                   ORDER BY s.created_at DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_showcases_by_user(self, user_id: str):
        """列出某用户的所有作品。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT s.*, a.name as agent_name
                   FROM showcases s
                   LEFT JOIN agents a ON s.agent_id = a.id
                   WHERE s.user_id = ?
                   ORDER BY s.created_at DESC""",
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]


    # ═════════════════════════════════════════════════════════════
    # invitation_codes 表 CRUD
    # ═════════════════════════════════════════════════════════════

    def generate_invitation_code(self) -> str:
        """生成唯一的 YQ+12位随机邀请码"""
        chars = string.ascii_letters + string.digits
        while True:
            code = "YQ" + ''.join(random.choices(chars, k=12))
            # 检查是否已存在
            existing = self.get_invitation_code(code)
            if existing is None:
                break
        return code

    def create_invitation_code(self, owner_id: str) -> str:
        """为用户创建邀请码，返回邀请码字符串"""
        code = self.generate_invitation_code()
        self._execute_write(
            "INSERT INTO invitation_codes (code, owner_id) VALUES (?, ?)",
            (code, owner_id),
        )
        return code

    def get_invitation_code(self, code: str):
        """按邀请码查询"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute(
                    "SELECT * FROM invitation_codes WHERE code = ?", (code,)
                ).fetchone()
            )

    def get_user_invitation_code(self, user_id: str):
        """查某个用户的邀请码"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute(
                    "SELECT * FROM invitation_codes WHERE owner_id = ? ORDER BY created_at DESC LIMIT 1",
                    (user_id,),
                ).fetchone()
            )

    def increment_invitation_use(self, code: str) -> None:
        """邀请码使用次数+1"""
        self._execute_write(
            "UPDATE invitation_codes SET use_count = use_count + 1 WHERE code = ?",
            (code,),
        )

    def record_invitation_use(self, code: str, inviter_id: str,
                              invitee_id: str) -> int:
        """记录邀请使用，返回记录ID"""
        with self._lock:
            with self.conn() as conn:
                conn.execute(
                    "INSERT INTO invitation_uses (code, inviter_id, invitee_id, bonus_given) VALUES (?, ?, ?, 1)",
                    (code, inviter_id, invitee_id),
                )
                return conn.lastrowid

    def get_invitation_stats(self) -> dict:
        """管理员查看邀请统计"""
        with self.conn() as conn:
            total_codes = conn.execute(
                "SELECT COUNT(*) FROM invitation_codes"
            ).fetchone()[0]
            total_uses = conn.execute(
                "SELECT COUNT(*) FROM invitation_uses"
            ).fetchone()[0]
            total_invitees = conn.execute(
                "SELECT COUNT(DISTINCT invitee_id) FROM invitation_uses"
            ).fetchone()[0]
            recent_uses = conn.execute(
                "SELECT iu.*, ic.owner_id as code_owner_id FROM invitation_uses iu "
                "LEFT JOIN invitation_codes ic ON iu.code = ic.code "
                "ORDER BY iu.created_at DESC LIMIT 20"
            ).fetchall()
        return {
            "total_codes": total_codes,
            "total_uses": total_uses,
            "total_invitees": total_invitees,
            "recent_uses": [dict(r) for r in recent_uses],
        }

    # ═════════════════════════════════════════════════════════════════
    # agent_souls 表 CRUD — SOUL.md 系统
    # ═════════════════════════════════════════════════════════════════

    def get_agent_soul(self, agent_id: str):
        """按 agent_id 查询 SOUL.md 记录。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM agent_souls WHERE agent_id = ?", (agent_id,)).fetchone()
            )

    def upsert_agent_soul(self, agent_id: str, content: str = "",
                          ironclad_rules: str = "") -> bool:
        """创建或更新 SOUL.md 记录。返回是否成功。"""
        existing = self.get_agent_soul(agent_id)
        if existing:
            sql = """UPDATE agent_souls SET
                     content = ?, ironclad_rules = ?,
                     version = version + 1,
                     updated_at = datetime('now','localtime')
                     WHERE agent_id = ?"""
            self._execute_write(sql, (content, ironclad_rules, agent_id))
        else:
            sql = """INSERT INTO agent_souls (agent_id, content, ironclad_rules)
                     VALUES (?, ?, ?)"""
            self._execute_write(sql, (agent_id, content, ironclad_rules))
        return True

    def update_agent_soul_content(self, agent_id: str, content: str) -> bool:
        """仅更新 SOUL.md 正文内容。"""
        sql = """UPDATE agent_souls SET content = ?, version = version + 1,
                 updated_at = datetime('now','localtime') WHERE agent_id = ?"""
        self._execute_write(sql, (content, agent_id))
        return True

    def update_agent_soul_ironclad(self, agent_id: str, rules: str) -> bool:
        """仅更新铁律（用户专属，AI 不可修改）。"""
        sql = """UPDATE agent_souls SET ironclad_rules = ?,
                 updated_at = datetime('now','localtime') WHERE agent_id = ?"""
        self._execute_write(sql, (rules, agent_id))
        return True

    # ═════════════════════════════════════════════════════════════════
    # agent_memories 表 CRUD — 分级记忆系统
    # ═════════════════════════════════════════════════════════════════

    def create_agent_memory(self, agent_id: str, user_id: str, content: str,
                            tier: int = 1, keywords: str = "",
                            importance: float = 0.5,
                            source: str = "",
                            access_count: int = 0) -> str:
        """创建一条分级记忆，返回记忆 ID。"""
        mid = self._new_id()
        sql = """INSERT INTO agent_memories (id, agent_id, user_id, tier, content,
                 keywords, importance, source, access_count)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        self._execute_write(sql, (mid, agent_id, user_id, tier, content,
                                  keywords, importance, source, access_count))
        return mid

    def list_agent_memories_by_tier(self, agent_id: str, user_id: str,
                                    tier: int, limit: int = 50) -> list:
        """按级别查询记忆，按重要度/最近访问排序。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT * FROM agent_memories
                   WHERE agent_id = ? AND user_id = ? AND tier = ?
                   ORDER BY importance DESC, accessed_at DESC
                   LIMIT ?""",
                (agent_id, user_id, tier, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_all_agent_memories(self, agent_id: str, user_id: str,
                                limit: int = 100) -> list:
        """列出某 agent 对某用户的所有分级记忆（按级别、重要度排序）。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT * FROM agent_memories
                   WHERE agent_id = ? AND user_id = ?
                   ORDER BY tier ASC, importance DESC, accessed_at DESC
                   LIMIT ?""",
                (agent_id, user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def search_agent_memories(self, agent_id: str, user_id: str,
                              keyword: str, limit: int = 20) -> list:
        """按关键词搜索分级记忆。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT * FROM agent_memories
                   WHERE agent_id = ? AND user_id = ?
                   AND (content LIKE ? OR keywords LIKE ?)
                   ORDER BY importance DESC, tier ASC, accessed_at DESC
                   LIMIT ?""",
                (agent_id, user_id, f"%{keyword}%", f"%{keyword}%", limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def touch_agent_memory(self, memory_id: str) -> bool:
        """更新记忆的最近访问时间。"""
        sql = """UPDATE agent_memories SET accessed_at = datetime('now','localtime')
                 WHERE id = ?"""
        self._execute_write(sql, (memory_id,))
        return True

    def demote_agent_memory(self, memory_id: str, new_tier: int) -> bool:
        """降级某条记忆的级别。"""
        sql = """UPDATE agent_memories SET tier = ?,
                 accessed_at = datetime('now','localtime') WHERE id = ?"""
        self._execute_write(sql, (new_tier, memory_id))
        return True

    def delete_agent_memory(self, memory_id: str) -> bool:
        """按 ID 删除记忆。"""
        self._execute_write("DELETE FROM agent_memories WHERE id = ?", (memory_id,))
        return True

    def count_agent_memories(self, agent_id: str, user_id: str,
                             tier: int = 0) -> int:
        """统计某 agent 对某用户的记忆数量。tier=0 表示全部级别。"""
        with self.conn() as conn:
            if tier:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM agent_memories WHERE agent_id = ? AND user_id = ? AND tier = ?",
                    (agent_id, user_id, tier),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM agent_memories WHERE agent_id = ? AND user_id = ?",
                    (agent_id, user_id),
                ).fetchone()
            return row["cnt"] if row else 0

    def total_agent_memories_chars(self, agent_id: str, user_id: str,
                                   tier: int = 0) -> int:
        """统计某 agent 对某用户的记忆总字符数。tier=0 表示全部级别。"""
        with self.conn() as conn:
            if tier:
                row = conn.execute(
                    "SELECT COALESCE(SUM(LENGTH(content)), 0) as total FROM agent_memories WHERE agent_id = ? AND user_id = ? AND tier = ?",
                    (agent_id, user_id, tier),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COALESCE(SUM(LENGTH(content)), 0) as total FROM agent_memories WHERE agent_id = ? AND user_id = ?",
                    (agent_id, user_id),
                ).fetchone()
            return row["total"] if row else 0

    def increment_agent_memory_access(self, memory_id: str) -> bool:
        """原子递增记忆访问次数并更新最后访问时间。"""
        sql = """UPDATE agent_memories
                 SET access_count = access_count + 1,
                     accessed_at = datetime('now','localtime')
                 WHERE id = ?"""
        self._execute_write(sql, (memory_id,))
        return True

    def get_agent_memory_by_id(self, memory_id: str) -> dict | None:
        """按 ID 查询单条分级记忆。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM agent_memories WHERE id = ?", (memory_id,)).fetchone()
            )

    # ═════════════════════════════════════════════════════════════════
    # memory_relations 表 CRUD — 关系图谱（cognee 模式）
    # ═════════════════════════════════════════════════════════════════

    def create_memory_relation(self, agent_id: str, user_id: str,
                               entity: str, relation: str, target: str) -> str:
        """创建一条关系三元组，返回 ID。"""
        rid = self._new_id()
        sql = """INSERT INTO memory_relations (id, agent_id, user_id, entity, relation, target)
                 VALUES (?, ?, ?, ?, ?, ?)"""
        self._execute_write(sql, (rid, agent_id, user_id, entity, relation, target))
        return rid

    def search_memory_relations_by_entity(self, agent_id: str, user_id: str,
                                          entity: str) -> list:
        """按实体名查询所有关联的关系。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT * FROM memory_relations
                   WHERE agent_id = ? AND user_id = ? AND entity LIKE ?
                   ORDER BY created_at DESC""",
                (agent_id, user_id, f"%{entity}%"),
            ).fetchall()
            return [dict(r) for r in rows]

    def search_memory_relations_by_relation(self, agent_id: str, user_id: str,
                                            relation: str) -> list:
        """按关系类型查询（如 '职业'）。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT * FROM memory_relations
                   WHERE agent_id = ? AND user_id = ? AND relation LIKE ?
                   ORDER BY created_at DESC""",
                (agent_id, user_id, f"%{relation}%"),
            ).fetchall()
            return [dict(r) for r in rows]

    def search_memory_relations_by_target(self, agent_id: str, user_id: str,
                                          target: str) -> list:
        """按目标值查询（如 '会计'）。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT * FROM memory_relations
                   WHERE agent_id = ? AND user_id = ? AND target LIKE ?
                   ORDER BY created_at DESC""",
                (agent_id, user_id, f"%{target}%"),
            ).fetchall()
            return [dict(r) for r in rows]

    def search_memory_relations_all(self, agent_id: str, user_id: str,
                                    keyword: str) -> list:
        """按关键词搜索所有关系字段（entity/relation/target）。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT * FROM memory_relations
                   WHERE agent_id = ? AND user_id = ?
                   AND (entity LIKE ? OR relation LIKE ? OR target LIKE ?)
                   ORDER BY created_at DESC""",
                (agent_id, user_id, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_memory_relation(self, relation_id: str) -> bool:
        """按 ID 删除关系。"""
        self._execute_write("DELETE FROM memory_relations WHERE id = ?", (relation_id,))
        return True

    def list_memory_relations(self, agent_id: str, user_id: str,
                              limit: int = 100) -> list:
        """列出某 agent 对某用户的所有关系。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT * FROM memory_relations
                   WHERE agent_id = ? AND user_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (agent_id, user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # ═════════════════════════════════════════════════════════════════
    # ai_memories 表 CRUD — AI 持久记忆
    # ═════════════════════════════════════════════════════════════════

    def create_memory(self, agent_id: str, user_id: str, key: str,
                      value: str, source: str = "",
                      confidence: int = 1) -> str:
        """创建或更新一条 AI 记忆，返回记忆 ID。

        如果同 agent_id + user_id + key 已存在，则更新 value 和 confidence。
        """
        mid = self._new_id()
        sql = """INSERT INTO ai_memories (id, agent_id, user_id, key, value, source, confidence)
                 VALUES (?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(id) DO NOTHING"""
        existing = self.get_memory_by_key(agent_id, user_id, key)
        if existing:
            self.update_memory(existing["id"], value=value, confidence=confidence, source=source)
            return existing["id"]
        self._execute_write(sql, (mid, agent_id, user_id, key, value, source, confidence))
        return mid

    def get_memory(self, memory_id: str):
        """按 ID 查询记忆。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM ai_memories WHERE id = ?", (memory_id,)).fetchone()
            )

    def get_memory_by_key(self, agent_id: str, user_id: str, key: str):
        """按 agent_id + user_id + key 查询记忆。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute(
                    "SELECT * FROM ai_memories WHERE agent_id = ? AND user_id = ? AND key = ?",
                    (agent_id, user_id, key),
                ).fetchone()
            )

    def list_memories(self, agent_id: str, user_id: str) -> list:
        """列出某 agent 对某用户的所有记忆。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_memories WHERE agent_id = ? AND user_id = ? ORDER BY updated_at DESC",
                (agent_id, user_id),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_memory(self, memory_id: str, **kwargs) -> bool:
        """按 ID 更新记忆字段。"""
        if not kwargs:
            return False
        kwargs["updated_at"] = "datetime('now','localtime')"
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE ai_memories SET {sets} WHERE id = ?"
        params = tuple(kwargs.values()) + (memory_id,)
        self._execute_write(sql, params)
        return True

    def delete_memory(self, memory_id: str) -> bool:
        """按 ID 删除记忆。"""
        self._execute_write("DELETE FROM ai_memories WHERE id = ?", (memory_id,))
        return True

    def search_memories(self, agent_id: str, user_id: str, keyword: str) -> list:
        """按关键词搜索记忆。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_memories WHERE agent_id = ? AND user_id = ? AND (key LIKE ? OR value LIKE ?) ORDER BY confidence DESC, updated_at DESC",
                (agent_id, user_id, f"%{keyword}%", f"%{keyword}%"),
            ).fetchall()
            return [dict(r) for r in rows]

    # ═════════════════════════════════════════════════════════════════
    # ai_conversations 表 CRUD — AI 对话历史汇总
    # ═════════════════════════════════════════════════════════════════

    def create_conversation(self, agent_id: str, user_id: str,
                            summary: str = "", key_points: str = "") -> str:
        """创建一条对话记录，返回对话 ID。"""
        cid = self._new_id()
        sql = """INSERT INTO ai_conversations (id, agent_id, user_id, summary, key_points)
                 VALUES (?, ?, ?, ?, ?)"""
        self._execute_write(sql, (cid, agent_id, user_id, summary, key_points))
        return cid

    def get_conversation(self, conversation_id: str):
        """按 ID 查询对话记录。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM ai_conversations WHERE id = ?", (conversation_id,)).fetchone()
            )

    def list_conversations(self, agent_id: str, user_id: str, limit: int = 20) -> list:
        """列出某 agent 和某用户的最近对话记录。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_conversations WHERE agent_id = ? AND user_id = ? ORDER BY started_at DESC LIMIT ?",
                (agent_id, user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_conversation(self, conversation_id: str, **kwargs) -> bool:
        """按 ID 更新对话记录。"""
        if not kwargs:
            return False
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE ai_conversations SET {sets} WHERE id = ?"
        params = tuple(kwargs.values()) + (conversation_id,)
        self._execute_write(sql, params)
        return True

    def finish_conversation(self, conversation_id: str, summary: str = "",
                            key_points: str = "") -> bool:
        """结束对话：设置 ended_at、summary、key_points。"""
        sql = """UPDATE ai_conversations SET
                 ended_at = datetime('now','localtime'),
                 summary = ?,
                 key_points = ?
                 WHERE id = ?"""
        self._execute_write(sql, (summary, key_points, conversation_id))
        return True

    # ═════════════════════════════════════════════════════════════════
    # spark_scores 表 CRUD — 星火鉴评分
    # ═════════════════════════════════════════════════════════════════

    def save_spark_score(self, tool_name: str, utility_score: float = 0,
                         industrial_score: float = 0, stability_score: float = 0,
                         speed_score: float = 0, update_score: float = 0,
                         security_score: float = 0, compatibility_score: float = 0,
                         review_score: float = 0, revolution_score: float = 0,
                         total_score: float = 0, grade: str = "F") -> None:
        """保存或更新星火鉴评分。"""
        sql = """INSERT INTO spark_scores
                 (tool_name, utility_score, industrial_score, stability_score,
                  speed_score, update_score, security_score, compatibility_score,
                  review_score, revolution_score, total_score, grade, evaluated_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
                 ON CONFLICT(tool_name) DO UPDATE SET
                     utility_score = excluded.utility_score,
                     industrial_score = excluded.industrial_score,
                     stability_score = excluded.stability_score,
                     speed_score = excluded.speed_score,
                     update_score = excluded.update_score,
                     security_score = excluded.security_score,
                     compatibility_score = excluded.compatibility_score,
                     review_score = excluded.review_score,
                     star_score = excluded.revolution_score,
                     total_score = excluded.total_score,
                     grade = excluded.grade,
                     evaluated_at = datetime('now','localtime')"""
        self._execute_write(sql, (tool_name, utility_score, industrial_score,
                                   stability_score, speed_score, update_score,
                                   security_score, compatibility_score,
                                   review_score, star_score, total_score, grade))

    def get_spark_score(self, tool_name: str) -> dict:
        """获取工具星火鉴评分。"""
        with self.conn() as conn:
            row = self._row_to_dict(
                conn.execute("SELECT * FROM spark_scores WHERE tool_name = ?", (tool_name,)).fetchone()
            )
            if row:
                return row
            return {"tool_name": tool_name, "total_score": 0, "grade": "N/A"}

    def list_spark_scores(self, limit: int = 50, offset: int = 0) -> list:
        """列出所有星火鉴评分，按总分降序。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM spark_scores ORDER BY total_score DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    # ═════════════════════════════════════════════════════════════════
    # spark_reviews 表 CRUD — 星火鉴用户评价
    # ═════════════════════════════════════════════════════════════════

    def create_spark_review(self, tool_name: str, user_id: str,
                            rating: int, comment: str = "",
                            thumbs_up: int = 0, thumbs_down: int = 0) -> dict:
        """提交用户评价。返回评价信息。"""
        if rating < 1 or rating > 5:
            raise ValueError("评分必须在 1-5 之间")
        review_id = self._short_id("SR")
        sql = """INSERT INTO spark_reviews (id, tool_name, user_id, rating, comment, thumbs_up, thumbs_down)
                 VALUES (?, ?, ?, ?, ?, ?, ?)"""
        self._execute_write(sql, (review_id, tool_name, user_id, rating, comment, thumbs_up, thumbs_down))
        return self.get_spark_review(review_id)

    def get_spark_review(self, review_id: str) -> dict:
        """按 ID 查询评价。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM spark_reviews WHERE id = ?", (review_id,)).fetchone()
            )

    def list_spark_reviews(self, tool_name: str, limit: int = 50) -> list:
        """列出某工具的所有评价。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM spark_reviews WHERE tool_name = ? ORDER BY created_at DESC LIMIT ?",
                (tool_name, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_spark_review_summary(self, tool_name: str) -> dict:
        """获取工具评价汇总：平均评分、总评价数、好评率。"""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT AVG(rating) as avg_rating, COUNT(*) as count FROM spark_reviews WHERE tool_name = ?",
                (tool_name,),
            ).fetchone()
            avg = round(row["avg_rating"], 2) if row and row["avg_rating"] else 0.0
            count = row["count"] if row else 0
            # 好评率：评分 >= 4 的比例
            if count > 0:
                good = conn.execute(
                    "SELECT COUNT(*) FROM spark_reviews WHERE tool_name = ? AND rating >= 4",
                    (tool_name,),
                ).fetchone()[0]
                good_rate = round(good / count * 100, 1)
            else:
                good_rate = 0.0
            return {"avg_rating": avg, "count": count, "good_rate": good_rate}

    # ═════════════════════════════════════════════════════════════════
    # spark_stars 表 CRUD — 星火鉴星数（类 GitHub Stars）
    # ═════════════════════════════════════════════════════════════════

    def star_tool(self, tool_name: str, user_id: str) -> bool:
        """用户标记星数（点赞工具）。返回是否新增标记。"""
        with self._lock:
            with self.conn() as conn:
                existing = conn.execute(
                    "SELECT 1 FROM spark_stars WHERE tool_name = ? AND user_id = ?",
                    (tool_name, user_id),
                ).fetchone()
                if existing:
                    return False  # 已标记过
                conn.execute(
                    "INSERT INTO spark_stars (tool_name, user_id) VALUES (?, ?)",
                    (tool_name, user_id),
                )
                return True

    def unstar_tool(self, tool_name: str, user_id: str) -> bool:
        """用户取消星数标记。"""
        self._execute_write(
            "DELETE FROM spark_stars WHERE tool_name = ? AND user_id = ?",
            (tool_name, user_id),
        )
        return True

    def get_star_count(self, tool_name: str) -> int:
        """获取工具星数。"""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM spark_stars WHERE tool_name = ?",
                (tool_name,),
            ).fetchone()
            return row[0] if row else 0

    def has_user_starred(self, tool_name: str, user_id: str) -> bool:
        """检查用户是否已标记星数。"""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM spark_stars WHERE tool_name = ? AND user_id = ?",
                (tool_name, user_id),
            ).fetchone()
            return row is not None

    def list_starred_tools(self, user_id: str, limit: int = 50) -> list:
        """列出用户标记过的工具。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT s.*, t.name as tool_display_name
                   FROM spark_stars s
                   LEFT JOIN marketplace_tools t ON s.tool_name = t.name
                   WHERE s.user_id = ? ORDER BY s.starred_at DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # ═════════════════════════════════════════════════════════════════
    # spark_repo_stars 表 CRUD — GitHub 星数同步
    # ═════════════════════════════════════════════════════════════════

    def save_repo_stars(self, tool_name: str, repo_url: str,
                        github_stars: int = 0) -> None:
        """保存或更新工具的 GitHub 星数。"""
        from datetime import datetime
        sql = """INSERT INTO spark_repo_stars (tool_name, repo_url, github_stars, last_synced)
                 VALUES (?, ?, ?, ?)
                 ON CONFLICT(tool_name) DO UPDATE SET
                     repo_url = excluded.repo_url,
                     github_stars = excluded.github_stars,
                     last_synced = excluded.last_synced"""
        self._execute_write(sql, (tool_name, repo_url,
                                  github_stars, datetime.now().isoformat()))

    def get_repo_stars(self, tool_name: str) -> dict:
        """获取工具的 GitHub 星数信息。"""
        with self.conn() as conn:
            row = self._row_to_dict(
                conn.execute("SELECT * FROM spark_repo_stars WHERE tool_name = ?",
                             (tool_name,)).fetchone()
            )
            if row:
                return row
            return {"tool_name": tool_name, "repo_url": "",
                    "github_stars": 0, "last_synced": None}

    def list_repo_stars(self, limit: int = 50, offset: int = 0) -> list:
        """列出所有 GitHub 星数记录。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM spark_repo_stars ORDER BY github_stars DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════════════

_db_instance: Optional[Database] = None
_db_lock = threading.Lock()


def get_db(db_path: Optional[str] = None) -> Database:
    """获取全局唯一的 Database 单例（双重检查锁，线程安全）。

    Args:
        db_path: 数据库路径，仅在首次创建时生效。

    Returns:
        Database 实例。
    """
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                _db_instance = Database(db_path)
    return _db_instance
