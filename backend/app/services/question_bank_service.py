from sqlalchemy.orm import Session
from app.models.models import QuestionBank, QuestionCategory, QuestionDifficulty, CodingTest, Position
from app.schemas.question_bank import QuestionBankCreate, QuestionBankUpdate
from uuid import UUID, uuid4
from fastapi import UploadFile, HTTPException
from app.config.tenant_session import get_tenant_id
from app.utils.file_storage import (
    UPLOAD_ROOT, delete_object_file, save_upload_file, stage_file_deletions,
    tenant_resource_files, unlink_file_locations,
)
import json

from typing import List
from app.services.tenant_reference_service import require_tenant_entity

def create_question_bank(
    db: Session,
    name: str,
    category: QuestionCategory,
    difficulty: QuestionDifficulty,
    tags: List[str],
    file: UploadFile,
    position_id: UUID
):
    require_tenant_entity(db, Position, position_id, "Position not found")
    tenant_id = get_tenant_id(db)
    stored = save_upload_file(file, tenant_id, "question_banks", resource_type="question_bank")

    # TODO: 解析文件内容，提取题目
    # 这里先模拟解析结果
    questions = []

    db_question_bank = QuestionBank(
        id=uuid4(),
        name=name,
        category=category,
        difficulty=difficulty,
        tags=tags,
        source_file=f"/api/files/{stored.id}",
        source_file_id=stored.id,
        questions=questions,
        position_id=position_id
    )
    stored.resource_id = db_question_bank.id
    db.add_all([stored, db_question_bank])
    try:
        db.commit()
    except Exception:
        db.rollback()
        delete_object_file(UPLOAD_ROOT, tenant_id, stored.object_key)
        raise
    db.refresh(db_question_bank)
    return db_question_bank

def get_question_banks(db: Session, skip: int = 0, limit: int = 100):
    return db.query(QuestionBank).offset(skip).limit(limit).all()

def get_question_bank(db: Session, question_bank_id: UUID):
    return db.query(QuestionBank).filter(QuestionBank.id == question_bank_id).first()

def update_question_bank(db: Session, question_bank_id: UUID, update_data: QuestionBankUpdate):
    """更新题库"""
    db_question_bank = db.query(QuestionBank).filter(QuestionBank.id == question_bank_id).first()
    if not db_question_bank:
        return None

    data = update_data.dict(exclude_unset=True)
    for key, value in data.items():
        setattr(db_question_bank, key, value)

    db.commit()
    db.refresh(db_question_bank)
    return db_question_bank

def delete_question_bank(db: Session, question_bank_id: UUID):
    db_question_bank = db.query(QuestionBank).filter(QuestionBank.id == question_bank_id).first()
    if not db_question_bank:
        return None

    linked_tests = db.query(CodingTest).filter(CodingTest.question_bank_id == question_bank_id).count()
    if linked_tests > 0:
        raise HTTPException(
            status_code=400,
            detail=f"无法删除：该题库已关联 {linked_tests} 个笔试题，请先解除关联"
        )

    tenant_id = get_tenant_id(db)
    file_locations = stage_file_deletions(
        db, tenant_resource_files(
            db, tenant_id, "question_bank", question_bank_id, "question_banks"
        )
    )
    db.delete(db_question_bank)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    unlink_file_locations(file_locations, root=UPLOAD_ROOT)
    return db_question_bank
