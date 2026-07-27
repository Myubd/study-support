"""
study-support / main.py
------------------------
学習支援プラグインの最小実装(新しいアプリ追加の手順そのものを検証する
ステップ1)。

意図的に「学習ログを1件記録する」機能だけを持つ。これまでのarchlife/
interview_appで確立した3つのパターン(memory書き込み・schedule書き込み・
documents書き込み)をそのまま使い、新しい設計パターンは一切増やさない。

- 理解度が低い(<=2)科目が2回以上記録されたら memory:write:study.* へ反映
- 復習日を指定したら schedule_items へ登録(既存の schedule_due_soon トリガーが
  そのまま使える。新しいオートメーショントリガーの実装は不要)
- 教材ファイル添付(documents:write)は今回のステップ1では未実装
  (最初から機能を広げすぎない、というこのエコシステム全体の方針に沿うため)
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from local_ai_core.bootstrap import bootstrap_app
from local_ai_core.paths import get_core_db_path
from local_ai_core.permissions import PermissionGate, PermissionDenied
from local_ai_core.memory import MemoryStore
from local_ai_core.schedule import ScheduleStore

APP_KEY = "study_support"
_PLUGIN_MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "plugin_manifest.json")
_STUDY_DB_PATH = os.environ.get("STUDY_DB_PATH", "/app/data/study.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("study_support")

_profile_id: Optional[int] = None
_gate: Optional[PermissionGate] = None


def _init_study_db() -> None:
    os.makedirs(os.path.dirname(_STUDY_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_STUDY_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS study_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            minutes INTEGER NOT NULL,
            understanding INTEGER NOT NULL,
            note TEXT,
            review_date TEXT,
            schedule_synced INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
        """
    )
    # 既存DBに新しく追加したカラムを補う簡易マイグレーション(このアプリには
    # まだ本格的なマイグレーション機構が無いため、都度PRAGMAで確認する)。
    cols = [row[1] for row in conn.execute("PRAGMA table_info(study_logs)").fetchall()]
    if "schedule_synced" not in cols:
        conn.execute("ALTER TABLE study_logs ADD COLUMN schedule_synced INTEGER")
    conn.commit()
    conn.close()


@contextmanager
def _study_db():
    conn = sqlite3.connect(_STUDY_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _profile_id, _gate
    _init_study_db()
    _profile_id = bootstrap_app(_PLUGIN_MANIFEST_PATH, default_profile_display_name="デフォルトプロフィール")
    _gate = PermissionGate(get_core_db_path())
    logger.info("study_support bootstrap done (profile_id=%s)", _profile_id)
    yield


app = FastAPI(title="Study Support backend", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"ok": True, "profile_id": _profile_id}


_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.get("/", response_class=HTMLResponse)
def frontend():
    """学習ログの記録・一覧を行う唯一の画面(static/index.html)。
    このアプリの範囲を「学習ログ1機能」に絞っている段階では、ビルド
    ツール無しの単一HTMLで十分(gatewayの統合コンソールと同じ考え方)。
    """
    index_path = os.path.join(_STATIC_DIR, "index.html")
    with open(index_path, encoding="utf-8") as f:
        return f.read()


class LogCreateBody(BaseModel):
    subject: str
    minutes: int
    understanding: int  # 1(理解できていない) 〜 5(完全に理解した)
    note: Optional[str] = None
    review_date: Optional[str] = None  # "YYYY-MM-DD"。指定した場合のみ復習予定として共通予定表に反映


def _sync_weak_subjects_to_memory() -> None:
    """理解度が低い(<=2)記録が2回以上ある科目を「苦手分野」として
    memory:write:study.* に反映する。

    interview_appの性格診断・archlifeの今日の提案と同じ「静かに諦める」設計:
    memory:write:study.* が未許可でもログ記録自体は失敗させない。

    削除によって苦手分野の条件を満たさなくなった場合は、古い値を残さず
    forget() で消す(以前はここで空リストのまま何もしない実装になっており、
    ログを削除しても古い苦手分野がメモリーに残り続けるバグがあった)。
    """
    with _study_db() as conn:
        rows = conn.execute(
            "SELECT subject, COUNT(*) as cnt FROM study_logs WHERE understanding <= 2 "
            "GROUP BY subject HAVING cnt >= 2 ORDER BY cnt DESC"
        ).fetchall()
    weak_subjects = [r["subject"] for r in rows]
    try:
        mem = MemoryStore(get_core_db_path(), gate=_gate)
        if weak_subjects:
            mem.set(_profile_id, APP_KEY, "study.weak_subjects", weak_subjects, confidence="ai_inferred")
        else:
            mem.forget(_profile_id, APP_KEY, "study.weak_subjects")
    except PermissionDenied:
        pass
    except Exception:
        logger.exception("study.weak_subjectsの同期に失敗(ログ記録自体には影響なし)")


def _sync_review_to_schedule(log_id: int, subject: str, review_date: str) -> bool:
    """指定された復習日を共通の schedule_items に反映する。
    archlifeのtodo同期(sync_todos)と同じパターン。新しいトリガー種別は
    追加していないため、既存の automation の schedule_due_soon がそのまま使える。

    戻り値は「実際に登録できたか」。以前はここで結果を確認せず、フロント側が
    常に「共通予定表にも登録済み」と表示していたため、権限未許可で
    サイレントに失敗していても分からないままだった(実際にこのバグが発生した)。
    呼び出し元がこの戻り値を study_logs.schedule_synced に保存し、
    正直な表示につなげる。
    """
    try:
        sched = ScheduleStore(get_core_db_path(), gate=_gate)
        sched.upsert(
            _profile_id, APP_KEY,
            source_ref_id=f"study_log:{log_id}",
            item_type="review",
            title=f"復習: {subject}",
            due_at=review_date,
        )
        return True
    except PermissionDenied:
        return False
    except Exception:
        logger.exception("復習予定の共通予定表への同期に失敗(ログ記録自体には影響なし)")
        return False


@app.post("/logs")
def create_log(body: LogCreateBody):
    if not (1 <= body.understanding <= 5):
        raise HTTPException(status_code=400, detail="understandingは1〜5で指定してください")

    with _study_db() as conn:
        cur = conn.execute(
            "INSERT INTO study_logs (subject, minutes, understanding, note, review_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (body.subject, body.minutes, body.understanding, body.note, body.review_date),
        )
        log_id = cur.lastrowid

    _sync_weak_subjects_to_memory()

    schedule_synced: Optional[bool] = None
    if body.review_date:
        schedule_synced = _sync_review_to_schedule(log_id, body.subject, body.review_date)
        with _study_db() as conn:
            conn.execute(
                "UPDATE study_logs SET schedule_synced = ? WHERE id = ?",
                (1 if schedule_synced else 0, log_id),
            )

    return {"id": log_id, "schedule_synced": schedule_synced}


@app.get("/logs")
def list_logs():
    with _study_db() as conn:
        rows = conn.execute("SELECT * FROM study_logs ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


@app.delete("/logs/{log_id}")
def delete_log(log_id: int):
    with _study_db() as conn:
        cur = conn.execute("DELETE FROM study_logs WHERE id = ?", (log_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="ログが見つかりません")

    # このログから作られた復習予定(schedule_items)があれば、あわせて
    # キャンセル扱いにする(共通予定表に「削除済みのログの復習予定」が
    # 残り続けないようにするため)。ハードデリートではなくstatus更新なのは、
    # ScheduleStoreがそもそも削除APIを持たない(archlifeのtodo同期等と
    # 同じ設計)ため。
    try:
        sched = ScheduleStore(get_core_db_path(), gate=_gate)
        sched.set_status(_profile_id, APP_KEY, source_ref_id=f"study_log:{log_id}", status="cancelled")
    except PermissionDenied:
        pass
    except Exception:
        logger.exception("復習予定のキャンセル同期に失敗(ログ削除自体には影響なし)")

    _sync_weak_subjects_to_memory()
    return {"ok": True}
