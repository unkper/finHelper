import sqlite3
from contextlib import closing
from flask import Flask, g, current_app  # 确保导入了 current_app
from flask.cli import with_appcontext
import click

SUPPORTED_CURRENCIES = ("CNY", "HKD", "USD")

def get_db() -> sqlite3.Connection:
    if "db" not in g:
        # 修改点 1：使用 current_app.config 替代 g.flask_app.config
        conn = sqlite3.connect(
            current_app.config["DATABASE_PATH"],
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db

def close_db(error) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db() -> None:
    schema = """
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        category TEXT NOT NULL DEFAULT 'bank',
        currency TEXT NOT NULL DEFAULT 'CNY',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_date TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS snapshot_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id INTEGER NOT NULL,
        account_id INTEGER NOT NULL,
        amount REAL NOT NULL DEFAULT 0,
        sort_order INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE RESTRICT
    );

    CREATE TABLE IF NOT EXISTS exchange_rates (
        target_date TEXT NOT NULL,
        base_currency TEXT NOT NULL,
        rates TEXT NOT NULL,
        PRIMARY KEY (target_date, base_currency)
    );
    
    -- 1. 投资主题表
    CREATE TABLE IF NOT EXISTS themes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        status TEXT NOT NULL DEFAULT 'observing', -- observing(观察期), accumulating(建仓期), holding(持有期), closed(已平仓)
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    -- 2. 主题关联文章表
    CREATE TABLE IF NOT EXISTS theme_articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        theme_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        url TEXT,
        summary TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(theme_id) REFERENCES themes(id) ON DELETE CASCADE
    );

    -- 3. 主题关联标的（股票池）
    CREATE TABLE IF NOT EXISTS theme_assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        theme_id INTEGER NOT NULL,
        ticker TEXT NOT NULL,           -- 例如 AAPL, NVDA, 0700.HK
        exchange TEXT DEFAULT 'US',     -- 市场
        target_buy_price REAL,          -- 目标买入价
        target_sell_price REAL,         -- 目标卖出/止盈价
        FOREIGN KEY(theme_id) REFERENCES themes(id) ON DELETE CASCADE
    );

    -- 4. 主题时间线/里程碑
    CREATE TABLE IF NOT EXISTS theme_milestones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        theme_id INTEGER NOT NULL,
        event_date TEXT NOT NULL,       -- 发生日期
        description TEXT NOT NULL,
        is_completed INTEGER DEFAULT 0, -- 0 未发生, 1 已发生
        FOREIGN KEY(theme_id) REFERENCES themes(id) ON DELETE CASCADE
    );
    """
    # 修改点 2：使用 current_app.config 替代 g.flask_app.config
    with closing(sqlite3.connect(current_app.config["DATABASE_PATH"])) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(schema)
        migrate_db(conn)
        conn.commit()

def migrate_db(conn: sqlite3.Connection) -> None:
    account_columns = {row["name"] for row in conn.execute("PRAGMA table_info(accounts)")}
    if "currency" not in account_columns:
        conn.execute("ALTER TABLE accounts ADD COLUMN currency TEXT NOT NULL DEFAULT 'CNY'")

    entry_columns = {row["name"] for row in conn.execute("PRAGMA table_info(snapshot_entries)")}
    if "amount" in entry_columns:
        return

    # 检查并迁移新字段 region
    if "region" not in account_columns:
        conn.execute("ALTER TABLE accounts ADD COLUMN region TEXT NOT NULL DEFAULT '中国'")
        # 智能初始化：根据币种自动修正存量账户的国家
        conn.execute("UPDATE accounts SET region = '香港' WHERE currency = 'HKD'")
        conn.execute("UPDATE accounts SET region = '美国' WHERE currency = 'USD'")

    if {"cny_amount", "hkd_amount", "usd_amount"}.issubset(entry_columns):
        legacy_rows = conn.execute(
            """
            SELECT e.id, e.snapshot_id, e.account_id, e.cny_amount, e.hkd_amount, e.usd_amount, e.sort_order
            FROM snapshot_entries e
            ORDER BY e.id ASC
            """
        ).fetchall()

        conn.executescript(
            """
            ALTER TABLE snapshot_entries RENAME TO snapshot_entries_legacy;
            CREATE TABLE snapshot_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE,
                FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE RESTRICT
            );
            """
        )

        for row in legacy_rows:
            candidates = [
                ("CNY", row["cny_amount"]),
                ("HKD", row["hkd_amount"]),
                ("USD", row["usd_amount"]),
            ]
            chosen_currency = "CNY"
            chosen_amount = 0.0
            for currency, amount in candidates:
                if abs(amount or 0) > 0:
                    chosen_currency = currency
                    chosen_amount = amount
                    break

            conn.execute(
                "UPDATE accounts SET currency = ? WHERE id = ?",
                (chosen_currency, row["account_id"]),
            )
            conn.execute(
                """
                INSERT INTO snapshot_entries (id, snapshot_id, account_id, amount, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                (row["id"], row["snapshot_id"], row["account_id"], chosen_amount, row["sort_order"]),
            )

        conn.execute("DROP TABLE snapshot_entries_legacy")

@click.command("init-db")
@with_appcontext
def init_db_command():
    init_db()
    click.echo("Initialized the database.")