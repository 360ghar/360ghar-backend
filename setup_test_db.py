import psycopg
import sys

passwords = ['postgres', 'password', 'root', 'admin', '1234', '123456', '']
success = False
for pwd in passwords:
    try:
        conn = psycopg.connect(f'postgresql://postgres:{pwd}@localhost:5432/postgres')
        print(f'SUCCESS with password: "{pwd}"')
        conn.autocommit = True
        
        # Create user
        try:
            conn.execute("CREATE USER test_user WITH PASSWORD 'test_password'")
            print('Created test_user')
        except psycopg.errors.DuplicateObject:
            print('test_user already exists')
            
        # Create db
        try:
            conn.execute("CREATE DATABASE test_db OWNER test_user")
            print('Created test_db')
        except psycopg.errors.DuplicateDatabase:
            print('test_db already exists')
            
        # Grant privs
        conn.execute("GRANT ALL PRIVILEGES ON DATABASE test_db TO test_user")
        print('Granted privileges')
        
        # Create extensions
        try:
            conn_test = psycopg.connect(f'postgresql://postgres:{pwd}@localhost:5432/test_db')
            conn_test.autocommit = True
            conn_test.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            conn_test.execute("CREATE EXTENSION IF NOT EXISTS vector")
            print('Created extensions')
            conn_test.close()
        except Exception as e:
            print(f'Warning: Could not create extensions: {e}')
        
        conn.close()
        success = True
        break
    except psycopg.OperationalError:
        pass

if not success:
    print('FAILED to guess local postgres password')
    sys.exit(1)
