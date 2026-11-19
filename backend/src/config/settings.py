import os
DATABASE_URL=os.getenv('DATABASE_URL','mysql+pymysql://schemaworkbook:schemaworkbook_demo_pw@localhost:17743/schemaworkbook')
# Privileged DSN used only by the worker to create/drop isolated trial schemas and
# restricted play accounts. Defaults to DATABASE_URL when not provided (compose).
TRIAL_ADMIN_URL=os.getenv('TRIAL_ADMIN_URL',DATABASE_URL)
REDIS_URL=os.getenv('REDIS_URL','redis://redis:6379/0')
JWT_SECRET=os.getenv('JWT_SECRET','local-schema-workbook-change-before-public-use')
