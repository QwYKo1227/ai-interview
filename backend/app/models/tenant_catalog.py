"""Current tenant-isolation catalog shared by runtime audit tooling and tests.

Historical Alembic revisions deliberately retain frozen copies of these
values.  A new tenant-scoped table or reference requires a new migration and
an update here; tests compare the current catalog with the latest migration
snapshot so the two cannot drift silently.
"""

TENANT_TABLES = (
    "users",
    "positions",
    "question_banks",
    "resumes",
    "department_reviews",
    "interviews",
    "interview_panels",
    "offers",
    "offer_decision_audits",
    "offer_templates",
    "coding_tests",
    "coding_submissions",
    "system_configs",
    "workflows",
    "workflow_nodes",
    "workflow_edges",
    "workflow_executions",
    "workflow_node_executions",
    "stored_files",
)

GLOBAL_TABLES = (
    "tenants",
    "tenant_domains",
    "platform_users",
    "platform_audit_logs",
    "public_access_tokens",
)

# child table, local id column, parent table
COMPOSITE_TENANT_REFERENCES = (
    ("positions", "hiring_manager_id", "users"),
    ("question_banks", "source_file_id", "stored_files"),
    ("question_banks", "position_id", "positions"),
    ("resumes", "position_id", "positions"),
    ("resumes", "file_id", "stored_files"),
    ("resumes", "rejected_by", "users"),
    ("department_reviews", "resume_id", "resumes"),
    ("department_reviews", "reviewer_id", "users"),
    ("interviews", "resume_id", "resumes"),
    ("interviews", "position_id", "positions"),
    ("interviews", "interviewer_id", "users"),
    ("interview_panels", "interview_id", "interviews"),
    ("interview_panels", "interviewer_id", "users"),
    ("offers", "resume_id", "resumes"),
    ("offers", "position_id", "positions"),
    ("offers", "created_by", "users"),
    ("offer_decision_audits", "offer_id", "offers"),
    ("offer_decision_audits", "actor_id", "users"),
    ("offer_templates", "position_id", "positions"),
    ("offer_templates", "created_by", "users"),
    ("coding_tests", "question_bank_id", "question_banks"),
    ("coding_tests", "created_by", "users"),
    ("coding_tests", "resume_id", "resumes"),
    ("coding_tests", "position_id", "positions"),
    ("coding_submissions", "coding_test_id", "coding_tests"),
    ("workflows", "created_by", "users"),
    ("workflow_nodes", "workflow_id", "workflows"),
    ("workflow_edges", "workflow_id", "workflows"),
    ("workflow_executions", "workflow_id", "workflows"),
    ("workflow_executions", "triggered_by", "users"),
    ("workflow_node_executions", "execution_id", "workflow_executions"),
)
