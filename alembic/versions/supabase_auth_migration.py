"""Add Supabase Auth integration

Revision ID: add_supabase_auth
Revises: previous_revision
Create Date: 2024-12-29 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_supabase_auth'
down_revision = 'previous_revision'  # Update this with actual previous revision
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add supabase_user_id column to users table
    op.add_column('users', sa.Column('supabase_user_id', sa.String(), nullable=True))
    
    # Create unique index for supabase_user_id
    op.create_index('users_supabase_user_id_idx', 'users', ['supabase_user_id'], unique=True)
    
    # Make email nullable temporarily during migration
    op.alter_column('users', 'email', nullable=True)
    
    # Note: After migration is complete and all users have supabase_user_id:
    # 1. Make supabase_user_id NOT NULL
    # 2. Drop hashed_password column
    # 3. Make email NOT NULL again
    
    print("Migration completed. Next steps:")
    print("1. Ensure all users are migrated to Supabase Auth")
    print("2. Run the cleanup migration to remove hashed_password column")


def downgrade() -> None:
    # Remove the index
    op.drop_index('users_supabase_user_id_idx', table_name='users')
    
    # Remove the column
    op.drop_column('users', 'supabase_user_id')
    
    # Make email required again
    op.alter_column('users', 'email', nullable=False)