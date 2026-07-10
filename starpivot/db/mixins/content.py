"""StarPivot Engine - Database content mixin"""
import sqlite3
import uuid
import json
import time
import os
from datetime import datetime, timedelta
from typing import Any, Optional


class ContentMixin:
    """Mixin providing content-related database operations."""
    
    # All methods in this mixin access self.conn, self._execute_write, etc.
    # from the parent Database class.
    
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


