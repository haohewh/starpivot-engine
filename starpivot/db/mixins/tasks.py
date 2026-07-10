"""StarPivot Engine - Database tasks mixin"""
import sqlite3
import uuid
import json
import time
import os
from datetime import datetime, timedelta
from typing import Any, Optional


class TasksMixin:
    """Mixin providing tasks-related database operations."""
    
    # All methods in this mixin access self.conn, self._execute_write, etc.
    # from the parent Database class.
    
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

