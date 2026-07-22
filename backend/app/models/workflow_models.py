from sqlalchemy import Column, String, Boolean, DateTime, Text, Enum, JSON, Integer, ForeignKeyConstraint, Float, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, ARRAY
import uuid
from datetime import datetime
from app.models.base import Base
import enum
from sqlalchemy.orm import relationship
from app.models.tenant_models import TenantScopedMixin


def _tenant_identity(table_name):
    return UniqueConstraint(
        "tenant_id", "id", name=f"uq_{table_name}_tenant_id_id"
    )


def _tenant_reference(table_name, column_name, target_table):
    return ForeignKeyConstraint(
        ["tenant_id", column_name],
        [f"{target_table}.tenant_id", f"{target_table}.id"],
        name=f"fk_{table_name}_{column_name}_tenant",
    )


class WorkflowStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ExecutionStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeType(str, enum.Enum):
    START = "start"
    END = "end"
    LLM = "llm"
    CONDITION = "condition"
    TOOL = "tool"
    HTTP_REQUEST = "http_request"
    EMAIL = "email"
    DATABASE = "database"
    CODE = "code"
    VARIABLE = "variable"
    LOOP = "loop"
    PARALLEL = "parallel"
    HUMAN_INPUT = "human_input"


class Workflow(TenantScopedMixin, Base):
    __tablename__ = "workflows"
    __table_args__ = (
        _tenant_identity("workflows"),
        _tenant_reference("workflows", "created_by", "users"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    description = Column(Text)
    status = Column(
        Enum(WorkflowStatus, values_callable=lambda enum_type: [e.value for e in enum_type]),
        default=WorkflowStatus.DRAFT,
    )
    
    graph = Column(JSON, default=dict)
    variables = Column(JSON, default=dict)
    
    trigger_type = Column(String, default="manual")
    trigger_config = Column(JSON, default=dict)
    
    is_template = Column(Boolean, default=False)
    is_system = Column(Boolean, default=False)
    
    created_by = Column(UUID(as_uuid=True))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_at = Column(DateTime)
    
    creator = relationship("User")
    executions = relationship(
        "WorkflowExecution",
        back_populates="workflow",
        foreign_keys="WorkflowExecution.workflow_id",
    )


class WorkflowNode(TenantScopedMixin, Base):
    __tablename__ = "workflow_nodes"
    __table_args__ = (
        _tenant_identity("workflow_nodes"),
        _tenant_reference("workflow_nodes", "workflow_id", "workflows"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), nullable=False)
    
    node_id = Column(String, nullable=False)
    node_type = Column(
        Enum(NodeType, values_callable=lambda enum_type: [e.value for e in enum_type]),
        nullable=False,
    )
    name = Column(String)
    description = Column(Text)
    
    position_x = Column(Float, default=0)
    position_y = Column(Float, default=0)
    
    config = Column(JSON, default=dict)
    input_schema = Column(JSON, default=dict)
    output_schema = Column(JSON, default=dict)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkflowEdge(TenantScopedMixin, Base):
    __tablename__ = "workflow_edges"
    __table_args__ = (
        _tenant_identity("workflow_edges"),
        _tenant_reference("workflow_edges", "workflow_id", "workflows"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), nullable=False)
    
    edge_id = Column(String, nullable=False)
    source_node_id = Column(String, nullable=False)
    target_node_id = Column(String, nullable=False)
    source_handle = Column(String)
    target_handle = Column(String)
    
    condition = Column(JSON, default=dict)
    label = Column(String)
    
    created_at = Column(DateTime, default=datetime.utcnow)


class WorkflowExecution(TenantScopedMixin, Base):
    __tablename__ = "workflow_executions"
    __table_args__ = (
        _tenant_identity("workflow_executions"),
        _tenant_reference("workflow_executions", "workflow_id", "workflows"),
        _tenant_reference("workflow_executions", "triggered_by", "users"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), nullable=False)
    
    status = Column(
        Enum(ExecutionStatus, values_callable=lambda enum_type: [e.value for e in enum_type]),
        default=ExecutionStatus.PENDING,
    )
    trigger_type = Column(String, default="manual")
    triggered_by = Column(UUID(as_uuid=True), nullable=True)
    
    input_data = Column(JSON, default=dict)
    output_data = Column(JSON, default=dict)
    variables = Column(JSON, default=dict)
    
    current_node_id = Column(String)
    executed_nodes = Column(JSON, default=list)
    
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    workflow = relationship(
        "Workflow", back_populates="executions", foreign_keys=[workflow_id]
    )
    trigger_user = relationship("User", foreign_keys=[triggered_by])
    node_executions = relationship("WorkflowNodeExecution", back_populates="execution")


class WorkflowNodeExecution(TenantScopedMixin, Base):
    __tablename__ = "workflow_node_executions"
    __table_args__ = (
        _tenant_identity("workflow_node_executions"),
        _tenant_reference(
            "workflow_node_executions", "execution_id", "workflow_executions"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id = Column(UUID(as_uuid=True), nullable=False)
    
    node_id = Column(String, nullable=False)
    node_type = Column(String, nullable=False)
    
    status = Column(String, default="pending")
    input_data = Column(JSON, default=dict)
    output_data = Column(JSON, default=dict)
    error_message = Column(Text)
    
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    execution = relationship("WorkflowExecution", back_populates="node_executions")
