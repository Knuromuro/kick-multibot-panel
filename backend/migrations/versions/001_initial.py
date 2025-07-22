"""initial tables"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table(
        'groups',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('target', sa.String(length=80), nullable=False),
        sa.Column('interval', sa.Integer, default=600),
    )
    op.create_index('ix_groups_name', 'groups', ['name'], unique=True)
    op.create_table(
        'accounts',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('username', sa.String(length=120), nullable=False),
        sa.Column('password', sa.String(length=120), nullable=False),
        sa.Column('proxy', sa.String(length=200)),
        sa.Column('messages_file', sa.String(length=200)),
        sa.Column('group_id', sa.Integer, sa.ForeignKey('groups.id')),
    )
    op.create_index('ix_accounts_username', 'accounts', ['username'])
    op.create_table(
        'logs',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('account_id', sa.Integer, sa.ForeignKey('accounts.id')),
        sa.Column('timestamp', sa.DateTime, nullable=False),
        sa.Column('message', sa.String(length=200)),
    )
    op.create_index('ix_logs_timestamp', 'logs', ['timestamp'])
    op.create_table(
        'sync_events',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('event_id', sa.String(length=64), nullable=False),
        sa.Column('entity', sa.String(length=50), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('payload', sa.JSON),
        sa.Column('timestamp', sa.DateTime, nullable=False),
        sa.Column('synced', sa.Boolean, default=False),
    )
    op.create_index('ix_sync_events_event_id', 'sync_events', ['event_id'], unique=True)

def downgrade():
    op.drop_table('sync_events')
    op.drop_table('logs')
    op.drop_table('accounts')
    op.drop_table('groups')
