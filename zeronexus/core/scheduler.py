"""ZeroNexus Background Asynchronous Scheduler.

Handles periodic maintenance, daily quota resets at 00:00,
Minecraft server monitoring, and CWA earthquake rapid detection polling.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timedelta
from typing import Any, Callable, Coroutine, Dict, List, Optional

import pytz

from zeronexus.core.logger import log

ScheduledJobFunc = Callable[[], Coroutine[Any, Any, None]]


@dataclass
class ScheduledJob:
    name: str
    func: ScheduledJobFunc
    interval_seconds: Optional[float] = None
    daily_at_time: Optional[dt_time] = None  # e.g., dt_time(0, 0) for 00:00
    timezone_name: str = "Asia/Taipei"
    last_run: Optional[float] = None
    next_run: float = 0.0
    run_count: int = 0
    error_count: int = 0
    enabled: bool = True
    is_running: bool = False
    timeout_seconds: Optional[float] = 300.0
    _lock: Optional[asyncio.Lock] = field(default=None, repr=False)

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def job_id(self) -> str:
        """相容別名：獲取工作唯一識別名稱。"""
        return self.name

    def calculate_next_run(self, from_time: Optional[float] = None) -> float:
        now_ts = from_time if from_time is not None else time.time()
        try:
            tz = pytz.timezone(self.timezone_name)
        except Exception:
            tz = pytz.timezone("Asia/Taipei")

        if self.interval_seconds is not None:
            return now_ts + self.interval_seconds

        if self.daily_at_time is not None:
            now_dt = datetime.fromtimestamp(now_ts, tz=tz)
            target_naive = datetime.combine(now_dt.date(), self.daily_at_time)
            target_dt = tz.localize(target_naive)
            if target_dt <= now_dt:
                target_naive = datetime.combine(now_dt.date() + timedelta(days=1), self.daily_at_time)
                target_dt = tz.localize(target_naive)
            return target_dt.timestamp()

        return now_ts + 60.0


class Scheduler:
    """Async scheduler managing non-blocking recurring jobs."""

    def __init__(self) -> None:
        self._jobs: Dict[str, ScheduledJob] = {}
        self._loop_task: Optional[asyncio.Task[None]] = None
        self._running_tasks: set[asyncio.Task[None]] = set()
        self._running: bool = False

    def add_interval_job(
        self,
        name: str,
        func: ScheduledJobFunc,
        seconds: float,
        run_immediately: bool = False,
        timeout_seconds: Optional[float] = 300.0,
    ) -> None:
        """Registers a recurring task that runs every `seconds` seconds."""
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"Scheduled job function '{name}' must be an async coroutine function.")

        now = time.time()
        next_run = now if run_immediately else (now + seconds)
        job = ScheduledJob(
            name=name,
            func=func,
            interval_seconds=seconds,
            next_run=next_run,
            timeout_seconds=timeout_seconds,
        )
        self._jobs[name] = job
        log.info(f"⏱️  已註冊週期性背景任務：'{name}'（每 {seconds} 秒執行一次）")

    def add_daily_job(
        self,
        name: str,
        func: ScheduledJobFunc,
        hour: int,
        minute: int,
        timezone_name: str = "Asia/Taipei",
        timeout_seconds: Optional[float] = 300.0,
    ) -> None:
        """Registers a daily task that runs once a day at hour:minute in the specified timezone."""
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"Scheduled job function '{name}' must be an async coroutine function.")

        job = ScheduledJob(
            name=name,
            func=func,
            daily_at_time=dt_time(hour, minute),
            timezone_name=timezone_name,
            timeout_seconds=timeout_seconds,
        )
        job.next_run = job.calculate_next_run()
        self._jobs[name] = job
        log.info(f"📅 已註冊每日定時任務：'{name}'（於每日 {hour:02d}:{minute:02d} [{timezone_name}] 執行）")

    async def start(self) -> None:
        """Starts the background scheduler loop."""
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._scheduler_loop(), name="zeronexus_scheduler")
        log.info("⏰ 背景排程管理器已成功啟動。")

    async def stop(self) -> None:
        """Stops the background scheduler loop gracefully."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.warning(f"Error awaiting scheduler loop shutdown: {e}")
            self._loop_task = None

        if self._running_tasks:
            tasks_to_cancel = list(self._running_tasks)
            log.info(f"Cancelling {len(tasks_to_cancel)} active scheduled background tasks...")
            for task in tasks_to_cancel:
                task.cancel()
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            self._running_tasks.clear()

        # Reset is_running and locks for all registered jobs to prevent stale state across restarts
        for job in self._jobs.values():
            job.is_running = False
            job._lock = None

        log.info("Scheduler stopped.")

    def _on_job_task_done(self, task: asyncio.Task[None]) -> None:
        """Completion callback for background tasks ensuring unhandled exceptions are logged and retrieved."""
        self._running_tasks.discard(task)
        if not task.cancelled():
            try:
                exc = task.exception()
                if exc:
                    log.error(f"Scheduled background task '{task.get_name()}' crashed with unhandled exception: {exc}", exc_info=exc)
            except (asyncio.CancelledError, Exception) as e:
                log.warning(f"Error checking background task result: {e}")

    async def _scheduler_loop(self) -> None:
        while self._running:
            try:
                now = time.time()
                for job in list(self._jobs.values()):
                    try:
                        if job.enabled and not job.is_running and not job.lock.locked() and now >= job.next_run:
                            # Safely calculate and advance next_run before spawning execution task
                            try:
                                next_ts = job.calculate_next_run(from_time=now)
                                if next_ts <= now:
                                    next_ts = now + (job.interval_seconds or 60.0)
                            except Exception as calc_err:
                                log.warning(f"Failed to calculate next run for job '{job.name}': {calc_err}")
                                next_ts = now + (job.interval_seconds or 60.0)

                            job.last_run = now
                            job.next_run = next_ts

                            task = asyncio.create_task(
                                self._execute_job(job),
                                name=f"scheduled_job_{job.name}",
                            )
                            self._running_tasks.add(task)
                            task.add_done_callback(self._on_job_task_done)
                    except Exception as job_err:
                        log.error(f"Error checking/scheduling job '{job.name}': {job_err}", exc_info=True)
                        job.next_run = now + (job.interval_seconds or 60.0)
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Error in scheduler main loop: {e}", exc_info=True)
                await asyncio.sleep(2.0)

    async def _execute_job(self, job: ScheduledJob) -> None:
        if job.is_running or job.lock.locked():
            log.warning(f"Job '{job.name}' is already running, skipping overlapping execution.")
            return

        async with job.lock:
            if job.is_running:
                log.warning(f"Job '{job.name}' re-entrancy detected after lock acquisition, skipping.")
                return
            job.is_running = True
            start_ts = time.perf_counter()
            try:
                log.debug(f"Executing scheduled job: '{job.name}'")
                if job.timeout_seconds and job.timeout_seconds > 0:
                    await asyncio.wait_for(job.func(), timeout=job.timeout_seconds)
                else:
                    await job.func()
                job.run_count += 1
                duration_ms = (time.perf_counter() - start_ts) * 1000
                log.debug(f"Job '{job.name}' finished in {duration_ms:.2f}ms")
            except asyncio.TimeoutError:
                job.error_count += 1
                log.error(f"Scheduled job '{job.name}' timed out after {job.timeout_seconds}s.", exc_info=True)
            except asyncio.CancelledError:
                log.info(f"Scheduled job '{job.name}' was cancelled gracefully.")
                raise
            except Exception as e:
                job.error_count += 1
                log.error(f"Error executing scheduled job '{job.name}': {e}", exc_info=True)
            finally:
                job.is_running = False

    async def trigger_job(self, name: str) -> bool:
        """Manually triggers an existing job immediately if enabled and not already running."""
        job = self._jobs.get(name)
        if not job or not job.enabled:
            return False
        if job.is_running or job.lock.locked():
            log.warning(f"Cannot trigger job '{name}': already running.")
            return False
        task = asyncio.create_task(
            self._execute_job(job),
            name=f"scheduled_job_{name}",
        )
        self._running_tasks.add(task)
        task.add_done_callback(self._on_job_task_done)
        return True

    def remove_job(self, name: str) -> bool:
        """Removes a registered scheduled job."""
        if name in self._jobs:
            del self._jobs[name]
            log.info(f"Removed scheduled job '{name}'")
            return True
        return False

    def pause_job(self, name: str) -> bool:
        """Pauses a scheduled job from recurring."""
        job = self._jobs.get(name)
        if job:
            job.enabled = False
            log.info(f"Paused scheduled job '{name}'")
            return True
        return False

    def resume_job(self, name: str) -> bool:
        """Resumes a paused scheduled job."""
        job = self._jobs.get(name)
        if job:
            job.enabled = True
            job.next_run = job.calculate_next_run()
            log.info(f"Resumed scheduled job '{name}'")
            return True
        return False

    def health_check(self) -> Dict[str, Any]:
        """Provides operational health metrics for background scheduler."""
        loop_alive = self._loop_task is not None and not self._loop_task.done()
        status = "GREEN" if (self._running and loop_alive) else ("YELLOW" if not self._running else "RED")
        return {
            "status": status,
            "running": self._running,
            "loop_alive": loop_alive,
            "active_tasks_count": len(self._running_tasks),
            "jobs_count": len(self._jobs),
            "jobs": [
                {
                    "name": j.name,
                    "is_running": j.is_running or j.lock.locked(),
                    "run_count": j.run_count,
                    "error_count": j.error_count,
                    "enabled": j.enabled,
                }
                for j in self._jobs.values()
            ],
        }

    def list_jobs(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        now = time.time()
        for job in self._jobs.values():
            result.append({
                "name": job.name,
                "interval_seconds": job.interval_seconds,
                "daily_at": f"{job.daily_at_time.strftime('%H:%M')} ({job.timezone_name})" if job.daily_at_time else None,
                "last_run": datetime.fromtimestamp(job.last_run, tz=pytz.UTC).isoformat() if job.last_run else None,
                "next_run_in_seconds": max(0, int(job.next_run - now)),
                "run_count": job.run_count,
                "error_count": job.error_count,
                "enabled": job.enabled,
                "is_running": job.is_running or job.lock.locked(),
            })
        return result


# Singleton scheduler instance
scheduler = Scheduler()
