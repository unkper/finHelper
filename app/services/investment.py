# app/services/investment.py
from app.database import get_db
from app.services.quotes import fetch_us_quotes


DEFAULT_ASSISTANT_NAME = "默认助手"


# --- 投资助手 (Assistants) ---

def get_default_assistant_id():
    db = get_db()
    row = db.execute(
        "SELECT id FROM investment_assistants WHERE is_default = 1 LIMIT 1"
    ).fetchone()
    if row:
        return row["id"]
    cursor = db.execute(
        """
        INSERT INTO investment_assistants (name, description, is_default)
        VALUES (?, '未分类的投资主题', 1)
        """,
        (DEFAULT_ASSISTANT_NAME,),
    )
    db.commit()
    return cursor.lastrowid


def fetch_all_assistants():
    db = get_db()
    return db.execute(
        """
        SELECT
            a.*,
            COALESCE(SUM(m.profit_loss), 0) AS total_pnl,
            COUNT(CASE WHEN m.profit_loss IS NOT NULL THEN 1 END) AS scored_milestones
        FROM investment_assistants a
        LEFT JOIN themes t ON t.assistant_id = a.id
        LEFT JOIN theme_milestones m ON m.theme_id = t.id
        GROUP BY a.id
        ORDER BY total_pnl DESC, a.is_default DESC, a.name ASC
        """
    ).fetchall()


def fetch_assistant_by_id(assistant_id):
    db = get_db()
    return db.execute(
        "SELECT * FROM investment_assistants WHERE id = ?",
        (assistant_id,),
    ).fetchone()


def create_assistant(name, description=None):
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO investment_assistants (name, description, is_default)
        VALUES (?, ?, 0)
        """,
        (name.strip(), (description or "").strip() or None),
    )
    db.commit()
    return cursor.lastrowid


def fetch_assistants_with_themes():
    """返回 [(assistant, [themes...]), ...] 供列表页分组展示；助手按累计盈亏排名。"""
    assistants = fetch_all_assistants()
    db = get_db()
    themes = db.execute(
        """
        SELECT
            t.*,
            COALESCE(SUM(m.profit_loss), 0) AS theme_score,
            COUNT(CASE WHEN m.profit_loss IS NOT NULL THEN 1 END) AS scored_milestones
        FROM themes t
        LEFT JOIN theme_milestones m ON m.theme_id = t.id
        GROUP BY t.id
        ORDER BY t.updated_at DESC
        """
    ).fetchall()
    grouped = {assistant["id"]: [] for assistant in assistants}
    for theme in themes:
        assistant_id = theme["assistant_id"]
        if assistant_id in grouped:
            grouped[assistant_id].append(theme)
    return [(assistant, grouped[assistant["id"]]) for assistant in assistants]


# --- 主题 (Themes) ---

def fetch_all_themes():
    """获取所有投资主题"""
    db = get_db()
    return db.execute(
        """
        SELECT t.*, a.name AS assistant_name
        FROM themes t
        JOIN investment_assistants a ON t.assistant_id = a.id
        ORDER BY t.updated_at DESC
        """
    ).fetchall()


def fetch_theme_by_id(theme_id):
    """获取单个主题的基础信息（含所属助手）。"""
    db = get_db()
    return db.execute(
        """
        SELECT t.*, a.name AS assistant_name
        FROM themes t
        JOIN investment_assistants a ON t.assistant_id = a.id
        WHERE t.id = ?
        """,
        (theme_id,),
    ).fetchone()


def create_theme(title, description, assistant_id=None):
    """创建新投资主题，未指定助手时归入默认助手。"""
    db = get_db()
    if not assistant_id:
        assistant_id = get_default_assistant_id()
    elif not fetch_assistant_by_id(assistant_id):
        assistant_id = get_default_assistant_id()

    cursor = db.execute(
        """
        INSERT INTO themes (title, description, assistant_id)
        VALUES (?, ?, ?)
        """,
        (title, description, assistant_id),
    )
    db.commit()
    return cursor.lastrowid


def move_theme_to_assistant(theme_id, assistant_id):
    """将主题移动到指定投资助手。"""
    if not fetch_assistant_by_id(assistant_id):
        return False
    db = get_db()
    row = db.execute("SELECT id FROM themes WHERE id = ?", (theme_id,)).fetchone()
    if not row:
        return False
    db.execute(
        """
        UPDATE themes
        SET assistant_id = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (assistant_id, theme_id),
    )
    db.commit()
    return True


def delete_theme(theme_id):
    """删除投资主题（子表 CASCADE 自动清理）。"""
    db = get_db()
    row = db.execute("SELECT id, title FROM themes WHERE id = ?", (theme_id,)).fetchone()
    if not row:
        return None
    db.execute("DELETE FROM themes WHERE id = ?", (theme_id,))
    db.commit()
    return row["title"]


def fetch_theme_score(theme_id):
    """主题评分 = 已填写盈亏的时间节点之和。"""
    db = get_db()
    row = db.execute(
        """
        SELECT
            COALESCE(SUM(profit_loss), 0) AS theme_score,
            COUNT(CASE WHEN profit_loss IS NOT NULL THEN 1 END) AS scored_milestones
        FROM theme_milestones
        WHERE theme_id = ?
        """,
        (theme_id,),
    ).fetchone()
    return dict(row) if row else {"theme_score": 0, "scored_milestones": 0}


# --- 关联内容 (Articles, Assets, Milestones) 相关 ---

def _fetch_price_alerts_for_asset(db, asset_id):
    return db.execute(
        """
        SELECT a.*,
               m.event_date AS milestone_event_date,
               m.end_date AS milestone_end_date,
               m.description AS milestone_description,
               m.reminder_time AS milestone_reminder_time
        FROM theme_asset_price_alerts a
        LEFT JOIN theme_milestones m ON a.milestone_id = m.id
        WHERE a.asset_id = ?
        ORDER BY a.alert_type, a.target_price
        """,
        (asset_id,),
    ).fetchall()


def build_milestone_index(milestones) -> dict[int, int]:
    """按时间线顺序为节点编号（从 1 开始）。"""
    return {m["id"]: i for i, m in enumerate(milestones, 1)}


def _fetch_theme_milestone_index(db, theme_id: int) -> dict[int, int]:
    rows = db.execute(
        "SELECT id FROM theme_milestones WHERE theme_id = ? ORDER BY event_date ASC",
        (theme_id,),
    ).fetchall()
    return {row["id"]: i for i, row in enumerate(rows, 1)}


def _milestone_alert_note(milestone: dict, seq: int | None = None) -> str:
    """生成随节点提醒的展示备注（精简为编号）。"""
    if seq is not None:
        return f"#{seq}"
    event_date = milestone["event_date"]
    end_date = milestone.get("end_date") or event_date
    if end_date != event_date:
        date_part = f"{event_date} ~ {end_date}"
    else:
        date_part = event_date
    desc = (milestone.get("description") or "").strip()
    if len(desc) > 40:
        desc = desc[:40] + "…"
    time_part = (milestone.get("reminder_time") or "12:00")[:5]
    return f"{date_part} {time_part} · {desc}" if desc else f"{date_part} {time_part}"


def _fetch_milestones_by_ids(db, theme_id: int, milestone_ids: list[int]) -> list[dict]:
    if not milestone_ids:
        return []
    placeholders = ",".join("?" * len(milestone_ids))
    rows = db.execute(
        f"""
        SELECT * FROM theme_milestones
        WHERE theme_id = ? AND id IN ({placeholders})
        """,
        (theme_id, *milestone_ids),
    ).fetchall()
    return [dict(r) for r in rows]


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


def add_asset_price_alert(
    asset_id,
    target_price,
    direction,
    note=None,
    alert_type="price",
    milestone_id=None,
    commit=True,
):
    """为标的添加一条提醒（价位或随时间节点）。"""
    if alert_type not in ("price", "milestone"):
        alert_type = "price"
    if direction not in ("below", "above"):
        direction = "below"
    db = get_db()
    db.execute(
        """
        INSERT INTO theme_asset_price_alerts
            (asset_id, target_price, direction, note, alert_type, milestone_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (asset_id, target_price, direction, note or None, alert_type, milestone_id),
    )
    if commit:
        db.commit()


def add_theme_asset(theme_id, ticker, exchange='US', price_alerts=None, milestone_ids=None):
    """为主题添加监控标的（可附带多条价格提醒及随节点提醒）。"""
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
            alert_type="price",
            commit=False,
        )
    milestones = _fetch_milestones_by_ids(db, theme_id, milestone_ids or [])
    index_map = _fetch_theme_milestone_index(db, theme_id)
    for milestone in milestones:
        seq = index_map.get(milestone["id"])
        add_asset_price_alert(
            asset_id,
            0,
            "below",
            _milestone_alert_note(milestone, seq),
            alert_type="milestone",
            milestone_id=milestone["id"],
            commit=False,
        )
    db.commit()
    return asset_id


def add_theme_milestone(
    theme_id,
    event_date,
    description,
    reminder_time='12:00',
    profit_loss=None,
    end_date=None,
):
    """为主题添加时间线节点"""
    if not end_date:
        end_date = event_date
    db = get_db()
    db.execute(
        """
        INSERT INTO theme_milestones
            (theme_id, event_date, end_date, description, reminder_time, profit_loss)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (theme_id, event_date, end_date, description, reminder_time, profit_loss)
    )
    db.execute(
        "UPDATE themes SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (theme_id,),
    )
    db.commit()


def update_theme_milestone(
    theme_id,
    milestone_id,
    event_date,
    description,
    reminder_time='12:00',
    profit_loss=None,
    is_completed=None,
    end_date=None,
):
    """编辑时间线节点（盈亏为空则不纳入评分）。"""
    if not end_date:
        end_date = event_date
    db = get_db()
    row = db.execute(
        "SELECT id FROM theme_milestones WHERE id = ? AND theme_id = ?",
        (milestone_id, theme_id),
    ).fetchone()
    if not row:
        return False

    completed_value = 1 if is_completed else 0 if is_completed is not None else None
    if completed_value is not None:
        db.execute(
            """
            UPDATE theme_milestones
            SET event_date = ?, end_date = ?, description = ?, reminder_time = ?,
                profit_loss = ?, is_completed = ?
            WHERE id = ?
            """,
            (event_date, end_date, description, reminder_time, profit_loss, completed_value, milestone_id),
        )
    else:
        db.execute(
            """
            UPDATE theme_milestones
            SET event_date = ?, end_date = ?, description = ?, reminder_time = ?, profit_loss = ?
            WHERE id = ?
            """,
            (event_date, end_date, description, reminder_time, profit_loss, milestone_id),
        )
    db.execute(
        "UPDATE themes SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (theme_id,),
    )
    db.commit()
    return True


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
    db.execute(
        "UPDATE themes SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (theme_id,),
    )
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


def fetch_tracked_assets_overview():
    """汇总所有主题下的监控标的（按 ticker 去重）。"""
    db = get_db()
    rows = db.execute(
        """
        SELECT
            s.id AS asset_id,
            s.ticker,
            s.exchange,
            t.id AS theme_id,
            t.title AS theme_title,
            a.name AS assistant_name
        FROM theme_assets s
        JOIN themes t ON s.theme_id = t.id
        JOIN investment_assistants a ON t.assistant_id = a.id
        ORDER BY s.ticker, t.title
        """
    ).fetchall()

    grouped = {}
    for row in rows:
        key = (row["ticker"].upper(), row["exchange"])
        if key not in grouped:
            grouped[key] = {
                "ticker": row["ticker"].upper(),
                "exchange": row["exchange"],
                "themes": [],
                "alerts": [],
            }
        grouped[key]["themes"].append({
            "theme_id": row["theme_id"],
            "theme_title": row["theme_title"],
            "assistant_name": row["assistant_name"],
            "asset_id": row["asset_id"],
        })

    for item in grouped.values():
        asset_ids = {theme["asset_id"] for theme in item["themes"]}
        placeholders = ",".join("?" for _ in asset_ids)
        alerts = db.execute(
            f"""
            SELECT target_price, direction, note
            FROM theme_asset_price_alerts
            WHERE asset_id IN ({placeholders})
            ORDER BY target_price
            """,
            tuple(asset_ids),
        ).fetchall()
        item["alerts"] = [dict(alert) for alert in alerts]

    return list(grouped.values())

