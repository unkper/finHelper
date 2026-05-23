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
        ticker TEXT NOT NULL,
        exchange TEXT NOT NULL DEFAULT 'US',
        FOREIGN KEY(theme_id) REFERENCES themes(id) ON DELETE CASCADE
    );

    -- 3b. 标的价格提醒（可多条）
    CREATE TABLE IF NOT EXISTS theme_asset_price_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_id INTEGER NOT NULL,
        target_price REAL NOT NULL,
        direction TEXT NOT NULL DEFAULT 'below', -- below: 跌至/跌破, above: 涨至/涨破
        note TEXT,
        last_triggered_at TEXT,
        FOREIGN KEY(asset_id) REFERENCES theme_assets(id) ON DELETE CASCADE
    );

    -- 4. 主题时间线/里程碑
    CREATE TABLE IF NOT EXISTS theme_milestones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        theme_id INTEGER NOT NULL,
        event_date TEXT NOT NULL,       -- 发生日期
        description TEXT NOT NULL,
        reminder_time TEXT NOT NULL DEFAULT '12:00', -- 飞书提醒时刻 (HH:MM)
        reminded_advance_at TEXT,       -- 已发送「提前3天」提醒的日期
        reminded_day_at TEXT,           -- 已发送「当天」提醒的日期
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

def _migrate_asset_price_alerts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS theme_asset_price_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL,
            target_price REAL NOT NULL,
            direction TEXT NOT NULL DEFAULT 'below',
            note TEXT,
            last_triggered_at TEXT,
            FOREIGN KEY(asset_id) REFERENCES theme_assets(id) ON DELETE CASCADE
        )
        """
    )
    asset_columns = {row["name"] for row in conn.execute("PRAGMA table_info(theme_assets)")}
    if not asset_columns:
        return
    if "target_buy_price" not in asset_columns and "target_sell_price" not in asset_columns:
        return

    rows = conn.execute(
        """
        SELECT id, target_buy_price, target_sell_price
        FROM theme_assets
        WHERE target_buy_price IS NOT NULL OR target_sell_price IS NOT NULL
        """
    ).fetchall()
    for row in rows:
        existing = conn.execute(
            "SELECT COUNT(*) AS cnt FROM theme_asset_price_alerts WHERE asset_id = ?",
            (row["id"],),
        ).fetchone()["cnt"]
        if existing:
            continue
        if row["target_buy_price"] is not None:
            conn.execute(
                """
                INSERT INTO theme_asset_price_alerts (asset_id, target_price, direction, note)
                VALUES (?, ?, 'below', '计划买入（迁移）')
                """,
                (row["id"], row["target_buy_price"]),
            )
        if row["target_sell_price"] is not None:
            conn.execute(
                """
                INSERT INTO theme_asset_price_alerts (asset_id, target_price, direction, note)
                VALUES (?, ?, 'above', '计划止盈（迁移）')
                """,
                (row["id"], row["target_sell_price"]),
            )


def migrate_db(conn: sqlite3.Connection) -> None:
    _migrate_asset_price_alerts(conn)

    milestone_columns = {row["name"] for row in conn.execute("PRAGMA table_info(theme_milestones)")}
    if milestone_columns:
        if "reminder_time" not in milestone_columns:
            conn.execute(
                "ALTER TABLE theme_milestones ADD COLUMN reminder_time TEXT NOT NULL DEFAULT '12:00'"
            )
        if "reminded_advance_at" not in milestone_columns:
            conn.execute("ALTER TABLE theme_milestones ADD COLUMN reminded_advance_at TEXT")
        if "reminded_day_at" not in milestone_columns:
            conn.execute("ALTER TABLE theme_milestones ADD COLUMN reminded_day_at TEXT")

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