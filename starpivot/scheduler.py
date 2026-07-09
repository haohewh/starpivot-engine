"""星枢自调度器 — Scheduler。

星枢内部的定时任务调度器，替代外部 cron。
支持：每 N 秒/分钟执行、指定时间执行、注册任务。

用法:
    scheduler = Scheduler()
    
    # 注册任务
    scheduler.every(30, "seconds").do(my_func, arg1, arg2)
    scheduler.every(5, "minutes").do(another_func)
    
    # 启动调度器
    scheduler.start()
    
    # 停止
    scheduler.stop()
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """单个定时任务定义。

    Attributes:
        name:        任务名称。
        func:        要执行的函数（同步或异步）。
        args:        位置参数。
        kwargs:      关键字参数。
        interval:    执行间隔（秒）。
        next_run:    下次执行的时间戳。
        last_run:    上次执行的时间戳（None 表示尚未执行）。
        times_run:   已执行次数。
        enabled:     是否启用。
        run_count:   运行次数限制（None 表示不限）。
    """
    name: str
    func: Callable[..., Any]
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    interval: float = 0.0
    next_run: float = 0.0
    last_run: float | None = None
    times_run: int = 0
    enabled: bool = True
    max_runs: int | None = None  # None = 不限


class Every:
    """调度器间隔设置器。

    由 Scheduler.every() 返回，用于链式设置执行计划。

    用法:
        scheduler.every(30, "seconds").do(my_func)
        scheduler.every(5, "minutes").do(another_func)
        scheduler.every(1, "hours").do(yet_another)
    """

    def __init__(self, scheduler: Scheduler, interval: int, unit: str) -> None:
        self._scheduler = scheduler
        self._interval = interval
        self._unit = unit
        self._seconds = self._to_seconds(interval, unit)

    def _to_seconds(self, interval: int, unit: str) -> float:
        unit = unit.lower().rstrip("s")  # "seconds" -> "second", "minutes" -> "minute"
        mapping = {
            "second": 1.0,
            "minute": 60.0,
            "hour": 3600.0,
            "day": 86400.0,
        }
        if unit not in mapping:
            raise ValueError(f"不支持的时间单位: {unit}（支持: second/minute/hour/day）")
        return interval * mapping[unit]

    def do(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> ScheduledTask:
        """安排任务以指定间隔执行。

        Args:
            func: 要执行的函数。
            *args, **kwargs: 传给函数的参数。

        Returns:
            创建的 ScheduledTask 对象。
        """
        return self._scheduler._register_internal(
            name=func.__name__,
            func=func,
            args=args,
            kwargs=kwargs,
            interval=self._seconds,
        )


class Scheduler:
    """星枢自调度器：管理所有定时任务。

    支持:
        - 每 N 秒/分钟/小时执行
        - 指定时间执行（每日定点）
        - 任务注册和注销
        - 后台自动运行

    用法:
        scheduler = Scheduler()

        # 每 30 秒执行
        scheduler.every(30, "seconds").do(my_func)

        # 每 5 分钟执行
        scheduler.every(5, "minutes").do(check_health)

        # 启动
        await scheduler.start()

        # 获取状态
        status = scheduler.get_status()

        # 停止
        await scheduler.stop()
    """

    def __init__(self) -> None:
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    # ── 注册 ─────────────────────────────────

    def every(self, interval: int, unit: str = "seconds") -> Every:
        """每 N 秒/分钟执行。

        Args:
            interval: 间隔数值。
            unit:     时间单位（"seconds", "minutes", "hours", "days"）。

        Returns:
            Every 对象，调用 .do(func) 来实际注册任务。

        示例:
            scheduler.every(30, "seconds").do(my_func)
            scheduler.every(5, "minutes").do(another_func)
        """
        return Every(self, interval, unit)

    def at(self, time_str: str) -> "AtBuilder":
        """在指定时间每天执行。

        Args:
            time_str: 时间字符串，格式 "HH:MM"（24小时制）。

        Returns:
            AtBuilder 对象，调用 .do(func) 来实际注册任务。

        示例:
            scheduler.at("03:00").do(daily_cleanup)
            scheduler.at("12:00").do(lunch_report)
        """
        return AtBuilder(self, time_str)

    def register(self, name: str, func: Callable[..., Any], schedule: str) -> ScheduledTask:
        """注册定时任务（通用接口）。

        Args:
            name:     任务名称（唯一）。
            func:     要执行的函数。
            schedule: 调度计划字符串。
                格式:
                    - "every 30s"    每 30 秒
                    - "every 5m"     每 5 分钟
                    - "every 1h"     每小时
                    - "at 03:00"     每天 3:00

        Returns:
            创建的 ScheduledTask 对象。
        """
        schedule = schedule.strip().lower()

        if schedule.startswith("every "):
            parts = schedule[6:].split()
            if len(parts) < 1:
                raise ValueError(f"无效的调度计划: {schedule}")
            raw_num = parts[0].rstrip("smhd")
            num = int(raw_num) if raw_num else int(parts[0])
            unit = parts[1] if len(parts) > 1 else "seconds"
            # 解析单位缩写
            unit_map = {
                "s": "seconds", "sec": "seconds", "second": "seconds", "seconds": "seconds",
                "m": "minutes", "min": "minutes", "minute": "minutes", "minutes": "minutes",
                "h": "hours", "hour": "hours", "hours": "hours",
                "d": "days", "day": "days", "days": "days",
            }
            unit = unit_map.get(unit, unit)
            seconds = Every(self, num, unit)._seconds
            return self._register_internal(name, func, interval=seconds)

        elif schedule.startswith("at "):
            time_str = schedule[3:].strip()
            return AtBuilder(self, time_str).do(func, name=name)

        else:
            raise ValueError(f"不支持的调度计划格式: {schedule}")

    def _register_internal(
        self,
        name: str,
        func: Callable[..., Any],
        args: tuple = (),
        kwargs: dict | None = None,
        interval: float = 0.0,
        next_run: float | None = None,
        max_runs: int | None = None,
    ) -> ScheduledTask:
        """内部注册方法。"""
        if not callable(func):
            raise TypeError(f"func 必须可调用，得到: {type(func)}")

        task = ScheduledTask(
            name=name,
            func=func,
            args=args,
            kwargs=kwargs or {},
            interval=interval,
            next_run=next_run or time.time(),
            max_runs=max_runs,
        )
        self._tasks[name] = task
        logger.info(
            "调度器: 已注册任务 '%s' (间隔: %.1fs)",
            name, interval,
        )
        return task

    def unregister(self, name: str) -> bool:
        """注销一个定时任务。

        Args:
            name: 任务名称。

        Returns:
            True 表示成功注销，False 表示未找到。
        """
        task = self._tasks.pop(name, None)
        if task:
            logger.info("调度器: 已注销任务 '%s'", name)
            return True
        return False

    # ── 启动/停止 ─────────────────────────────

    async def start(self) -> None:
        """启动调度器，在后台运行定时任务循环。"""
        if self._running:
            logger.warning("调度器已在运行中")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("调度器已启动（%d 个任务）", len(self._tasks))

    async def stop(self) -> None:
        """停止调度器。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("调度器已停止")

    # ── 运行循环 ─────────────────────────────

    async def _run_loop(self) -> None:
        """调度器主循环。"""
        while self._running:
            try:
                now = time.time()
                ready_tasks = [
                    t for t in self._tasks.values()
                    if t.enabled
                    and (t.max_runs is None or t.times_run < t.max_runs)
                    and t.next_run <= now
                ]

                for task in ready_tasks:
                    asyncio.create_task(self._execute_task(task))

                # 如果没有待执行任务，适当休眠
                if not ready_tasks:
                    await asyncio.sleep(0.5)
                else:
                    # 给任务执行一点时间
                    await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("调度器循环异常: %s", e, exc_info=True)
                await asyncio.sleep(1)

    async def _execute_task(self, task: ScheduledTask) -> None:
        """执行单个任务。"""
        try:
            logger.debug("调度器: 执行任务 '%s'", task.name)

            # 更新执行时间
            now = time.time()
            task.last_run = now
            task.times_run += 1
            task.next_run = now + task.interval

            # 执行（支持同步和异步函数）
            result = task.func(*task.args, **task.kwargs)
            if inspect.iscoroutine(result):
                await result

            logger.debug("调度器: 任务 '%s' 执行完成", task.name)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(
                "调度器: 任务 '%s' 执行失败: %s", task.name, e,
                exc_info=True,
            )

    # ── 状态 ─────────────────────────────────

    def get_status(self) -> dict:
        """获取调度器状态。

        Returns:
            - running (bool):   是否运行中。
            - tasks (list):     所有任务的状态列表。
            - total (int):      任务总数。
            - enabled (int):    启用的任务数。
        """
        tasks_status = []
        enabled_count = 0
        for t in self._tasks.values():
            if t.enabled:
                enabled_count += 1
            tasks_status.append({
                "name": t.name,
                "enabled": t.enabled,
                "interval": t.interval,
                "last_run": t.last_run,
                "next_run": t.next_run,
                "times_run": t.times_run,
                "max_runs": t.max_runs,
            })

        return {
            "running": self._running,
            "total": len(self._tasks),
            "enabled": enabled_count,
            "tasks": tasks_status,
        }

    def get_task(self, name: str) -> ScheduledTask | None:
        """获取指定任务。

        Args:
            name: 任务名称。

        Returns:
            ScheduledTask 或 None（未找到时）。
        """
        return self._tasks.get(name)


class AtBuilder:
    """指定时间调度构造器。

    由 scheduler.at("HH:MM") 返回。
    """

    def __init__(self, scheduler: Scheduler, time_str: str) -> None:
        self._scheduler = scheduler
        parts = time_str.strip().split(":")
        if len(parts) != 2:
            raise ValueError(
                f"时间格式无效: {time_str!r}。请使用 'HH:MM' 格式",
            )
        self._hour = int(parts[0])
        self._minute = int(parts[1])
        if not (0 <= self._hour < 24) or not (0 <= self._minute < 60):
            raise ValueError(f"时间不在有效范围: {time_str!r}")

    def do(
        self, func: Callable[..., Any], *args: Any, name: str | None = None, **kwargs: Any,
    ) -> ScheduledTask:
        """安排任务在指定时间执行。

        Args:
            func: 要执行的函数。
            *args, **kwargs: 传给函数的参数。
            name: 可选的任务名称（默认使用函数名）。

        Returns:
            创建的 ScheduledTask 对象。
        """
        task_name = name or func.__name__

        # 计算下次执行时间
        now = datetime.now()
        target = now.replace(
            hour=self._hour, minute=self._minute, second=0, microsecond=0,
        )
        if target <= now:
            target += timedelta(days=1)

        next_run = target.timestamp()

        return self._scheduler._register_internal(
            name=task_name,
            func=func,
            args=args,
            kwargs=kwargs,
            interval=86400.0,  # 每天一次
            next_run=next_run,
        )
