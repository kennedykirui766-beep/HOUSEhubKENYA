from sqlalchemy import create_engine

# Use your password here if it's set
db_url = "mysql+pymysql://root:@localhost/house_db"
engine = create_engine(db_url)

try:
    with engine.connect() as connection:
        print("✅ Connected to the database successfully.")
except Exception as e:
    print(f"❌ Failed to connect: {e}")