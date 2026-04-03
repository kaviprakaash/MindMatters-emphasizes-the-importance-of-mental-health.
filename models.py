import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os

DATABASE = 'mental_wellness.db'

def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with get_db() as db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        user_cols = {row['name'] for row in db.execute('PRAGMA table_info(users)').fetchall()}
        if 'google_sub' not in user_cols:
            db.execute('ALTER TABLE users ADD COLUMN google_sub TEXT')
        db.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub '
            'ON users(google_sub) WHERE google_sub IS NOT NULL'
        )
        db.execute('''
            CREATE TABLE IF NOT EXISTS mood_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mood TEXT NOT NULL,
                note TEXT,
                date TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                response TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS drug_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                normalized_query TEXT NOT NULL UNIQUE,
                openfda_query TEXT,
                source TEXT NOT NULL,
                use TEXT,
                side_effects TEXT,
                safety_warnings TEXT,
                fetched_at INTEGER NOT NULL
            )
        ''')

        # Lightweight migration for older databases that may miss new columns.
        columns = {row["name"] for row in db.execute("PRAGMA table_info(drug_cache)").fetchall()}
        if "openfda_query" not in columns:
            db.execute('ALTER TABLE drug_cache ADD COLUMN openfda_query TEXT')
        if "source" not in columns:
            db.execute('ALTER TABLE drug_cache ADD COLUMN source TEXT')
        if "use" not in columns:
            db.execute('ALTER TABLE drug_cache ADD COLUMN use TEXT')
        if "side_effects" not in columns:
            db.execute('ALTER TABLE drug_cache ADD COLUMN side_effects TEXT')
        if "safety_warnings" not in columns:
            db.execute('ALTER TABLE drug_cache ADD COLUMN safety_warnings TEXT')
        if "fetched_at" not in columns:
            db.execute('ALTER TABLE drug_cache ADD COLUMN fetched_at INTEGER')

        db.execute('''
            CREATE TABLE IF NOT EXISTS campus_chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id TEXT NOT NULL,
                nickname TEXT NOT NULL,
                body TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        db.execute(
            'CREATE INDEX IF NOT EXISTS idx_campus_chat_room_time '
            'ON campus_chat_messages(room_id, created_at)'
        )
        db.execute('''
            CREATE TABLE IF NOT EXISTS random_match_queue (
                user_id INTEGER PRIMARY KEY,
                nickname TEXT NOT NULL,
                queued_at INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS random_chat_pairs (
                pair_id TEXT PRIMARY KEY,
                user_a_id INTEGER NOT NULL,
                user_b_id INTEGER NOT NULL,
                nick_a TEXT NOT NULL,
                nick_b TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                ended_at INTEGER,
                FOREIGN KEY (user_a_id) REFERENCES users(id),
                FOREIGN KEY (user_b_id) REFERENCES users(id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS random_chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                body TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        db.execute(
            'CREATE INDEX IF NOT EXISTS idx_random_msg_pair '
            'ON random_chat_messages(pair_id, created_at)'
        )
        db.commit()

# Call init_db() when the app starts
if not os.path.exists(DATABASE):
    init_db()