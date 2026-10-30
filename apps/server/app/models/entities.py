"""SQLAlchemy ORM models: Project → Case / Task → Run → CaseResult."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    base_url: Mapped[str] = mapped_column(String(500), default="")
    default_browser: Mapped[str] = mapped_column(String(50), default="chromium")
    default_timeout_ms: Mapped[int] = mapped_column(Integer, default=30000)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    cases: Mapped[list[Case]] = relationship(back_populates="project", cascade="all, delete-orphan")
    tasks: Mapped[list[Task]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # steps: visual editor is source of truth; script: editable Playwright Python
    mode: Mapped[str] = mapped_column(String(20), default="steps")
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    script: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="cases")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    case_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    browser: Mapped[str] = mapped_column(String(50), default="chromium")
    headless: Mapped[bool] = mapped_column(Boolean, default=True)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=30000)
    # steps-mode capture options
    capture_screenshots: Mapped[bool] = mapped_column(Boolean, default=False)
    record_video: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="tasks")
    runs: Mapped[list[Run]] = relationship(back_populates="task", cascade="all, delete-orphan")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    error_summary: Mapped[str] = mapped_column(Text, default="")
    # [{ts?, level, message}] persisted run log lines for detail replay
    logs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Relative paths under repo root, e.g. artifacts/run-1/allure-results
    allure_results_path: Mapped[str] = mapped_column(String(500), default="")
    allure_report_path: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    task: Mapped[Task] = relationship(back_populates="runs")
    case_results: Mapped[list[CaseResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class CaseResult(Base):
    __tablename__ = "case_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    case_id: Mapped[int] = mapped_column(Integer)
    case_name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(50), default="pending")
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    error_type: Mapped[str] = mapped_column(String(100), default="")
    screenshot_path: Mapped[str] = mapped_column(String(500), default="")
    step_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # [{type: screenshot|video, path, label}]
    artifacts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    run: Mapped[Run] = relationship(back_populates="case_results")
