from __future__ import annotations

from backend.api.app.db.session import SessionLocal
from backend.api.app.db.models.entities import KnowledgePage
from backend.api.app.services.knowledge_service import KnowledgeService
from backend.worker.app.celery_app import celery_app


@celery_app.task(name="build_knowledge_chunks")
def build_knowledge_chunks(page_id: str) -> dict:
    db = SessionLocal()
    try:
        page = db.get(KnowledgePage, page_id)
        if not page:
            return {"status": "ignored", "reason": "page_not_found"}
        chunks = KnowledgeService().rebuild_chunks(db, page)
        db.commit()
        return {"status": "ok", "chunk_count": len(chunks)}
    finally:
        db.close()
