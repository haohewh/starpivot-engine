"""StarPivot Engine - Database finance mixin"""
import sqlite3
import uuid
import json
import time
import os
from datetime import datetime, timedelta
from typing import Any, Optional


class FinanceMixin:
    """Mixin providing finance-related database operations."""
    
    # All methods in this mixin access self.conn, self._execute_write, etc.
    # from the parent Database class.
    
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

