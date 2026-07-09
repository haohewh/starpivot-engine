"""StarPivot Engine - Database schema DDL"""
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

