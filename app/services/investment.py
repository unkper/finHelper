# app/services/investment.py
from app.database import get_db
from app.services.quotes import fetch_us_quotes


# --- 主题 (Themes) 相关 ---

def fetch_all_themes():
    """获取所有投资主题"""
    db = get_db()
    return db.execute("SELECT * FROM themes ORDER BY updated_at DESC").fetchall()


def fetch_theme_by_id(theme_id):
    """获取单个主题的基础信息"""
    db = get_db()
    return db.execute("SELECT * FROM themes WHERE id = ?", (theme_id,)).fetchone()


def create_theme(title, description, status='observing'):
    """创建新投资主题"""
    db = get_db()
    cursor = db.execute(
        "INSERT INTO themes (title, description, status) VALUES (?, ?, ?)",
        (title, description, status)
    )
    db.commit()
    return cursor.lastrowid


def update_theme_status(theme_id, new_status):
    """更新主题状态（如从观察期转为建仓期）"""
    db = get_db()
    db.execute(
        "UPDATE themes SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_status, theme_id)
    )
    db.commit()


# --- 关联内容 (Articles, Assets, Milestones) 相关 ---

def _fetch_price_alerts_for_asset(db, asset_id):
    return db.execute(
        """
        SELECT * FROM theme_asset_price_alerts
        WHERE asset_id = ?
        ORDER BY direction, target_price
        """,
        (asset_id,),
    ).fetchall()


def fetch_assets_with_alerts(theme_id):
    """获取主题下标的及各自的价格提醒列表。"""
    db = get_db()
    assets_raw = db.execute(
        "SELECT * FROM theme_assets WHERE theme_id = ? ORDER BY ticker",
        (theme_id,),
    ).fetchall()

    assets = []
    us_tickers = []
    for row in assets_raw:
        asset = dict(row)
        asset["price_alerts"] = [dict(a) for a in _fetch_price_alerts_for_asset(db, row["id"])]
        if asset.get("exchange") == "US":
            us_tickers.append(asset["ticker"].upper())
        assets.append(asset)

    quotes = fetch_us_quotes(us_tickers) if us_tickers else {}
    for asset in assets:
        if asset.get("exchange") == "US":
            asset["current_price"] = quotes.get(asset["ticker"].upper())
        else:
            asset["current_price"] = None

    return assets


def fetch_theme_details(theme_id):
    """一次性获取主题下的所有关联数据"""
    db = get_db()

    articles = db.execute("SELECT * FROM theme_articles WHERE theme_id = ?", (theme_id,)).fetchall()
    assets = fetch_assets_with_alerts(theme_id)
    milestones = db.execute(
        "SELECT * FROM theme_milestones WHERE theme_id = ? ORDER BY event_date ASC",
        (theme_id,),
    ).fetchall()

    return {
        "articles": articles,
        "assets": assets,
        "milestones": milestones
    }


def add_theme_asset(theme_id, ticker, exchange='US', price_alerts=None):
    """为主题添加监控标的（可附带多条价格提醒）。"""
    db = get_db()
    cursor = db.execute(
        "INSERT INTO theme_assets (theme_id, ticker, exchange) VALUES (?, ?, ?)",
        (theme_id, ticker, exchange)
    )
    asset_id = cursor.lastrowid
    for alert in price_alerts or []:
        add_asset_price_alert(
            asset_id,
            alert["target_price"],
            alert["direction"],
            alert.get("note"),
            commit=False,
        )
    db.commit()
    return asset_id


def add_asset_price_alert(asset_id, target_price, direction, note=None, commit=True):
    """为标的添加一条价格提醒。"""
    if direction not in ("below", "above"):
        direction = "below"
    db = get_db()
    db.execute(
        """
        INSERT INTO theme_asset_price_alerts (asset_id, target_price, direction, note)
        VALUES (?, ?, ?, ?)
        """,
        (asset_id, target_price, direction, note or None),
    )
    if commit:
        db.commit()


def add_theme_milestone(theme_id, event_date, description, reminder_time='12:00'):
    """为主题添加时间线节点"""
    db = get_db()
    db.execute(
        """
        INSERT INTO theme_milestones (theme_id, event_date, description, reminder_time)
        VALUES (?, ?, ?, ?)
        """,
        (theme_id, event_date, description, reminder_time)
    )
    db.commit()


def delete_theme_milestone(theme_id, milestone_id):
    """删除主题下的时间线节点。"""
    db = get_db()
    row = db.execute(
        "SELECT id FROM theme_milestones WHERE id = ? AND theme_id = ?",
        (milestone_id, theme_id),
    ).fetchone()
    if not row:
        return False
    db.execute("DELETE FROM theme_milestones WHERE id = ?", (milestone_id,))
    db.commit()
    return True


def delete_theme_asset(theme_id, asset_id):
    """删除主题下的监控标的（关联价格提醒一并删除）。"""
    db = get_db()
    row = db.execute(
        "SELECT id, ticker FROM theme_assets WHERE id = ? AND theme_id = ?",
        (asset_id, theme_id),
    ).fetchone()
    if not row:
        return None
    db.execute("DELETE FROM theme_assets WHERE id = ?", (asset_id,))
    db.commit()
    return row["ticker"]


def delete_theme_article(theme_id, article_id):
    """删除主题下的研报/资讯文章。"""
    db = get_db()
    row = db.execute(
        "SELECT id, title FROM theme_articles WHERE id = ? AND theme_id = ?",
        (article_id, theme_id),
    ).fetchone()
    if not row:
        return None
    db.execute("DELETE FROM theme_articles WHERE id = ?", (article_id,))
    db.commit()
    return row["title"]


def add_theme_article(theme_id, title, url=None, summary=None):
    """为主题添加研报/资讯文章"""
    db = get_db()
    db.execute(
        "INSERT INTO theme_articles (theme_id, title, url, summary) VALUES (?, ?, ?, ?)",
        (theme_id, title, url or None, summary or None)
    )
    db.commit()
