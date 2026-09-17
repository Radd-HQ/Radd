"""Keep resource restrictions after individual grants expire or are revoked."""
from alembic import op
import sqlalchemy as sa
revision = 'd1213access'
down_revision = 'd988emailimages'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('access_restrictions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('resource_type', sa.String(40), nullable=False),
        sa.Column('resource_id', sa.String(100), nullable=False),
        sa.Column('access', sa.String(20), nullable=False),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id', ondelete='CASCADE')),
        sa.UniqueConstraint('resource_type','resource_id','access','project_id',
            name='uq_access_restriction_scope', postgresql_nulls_not_distinct=True))
    op.execute("""INSERT INTO access_restrictions(id,resource_type,resource_id,access,project_id)
        SELECT gen_random_uuid(),resource_type,resource_id,access,project_id
        FROM access_grants WHERE effect='allow' AND resource_type IN ('page','attachment','field','builtin_field')
        GROUP BY resource_type,resource_id,access,project_id""")

def downgrade():
    op.drop_table('access_restrictions')
