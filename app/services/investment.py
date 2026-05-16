# app/services/investment.py
from app.database import get_db
from datetime import datetime


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

def fetch_theme_details(theme_id):
    """一次性获取主题下的所有关联数据"""
    db = get_db()

    articles = db.execute("SELECT * FROM theme_articles WHERE theme_id = ?", (theme_id,)).fetchall()
    assets = db.execute("SELECT * FROM theme_assets WHERE theme_id = ?", (theme_id,)).fetchall()
    milestones = db.execute("SELECT * FROM theme_milestones WHERE theme_id = ? ORDER BY event_date ASC",
                            (theme_id,)).fetchall()

    return {
        "articles": articles,
        "assets": assets,
        "milestones": milestones
    }


def add_theme_asset(theme_id, ticker, exchange, target_buy, target_sell):
    """为主题添加监控标的"""
    db = get_db()
    db.execute(
        "INSERT INTO theme_assets (theme_id, ticker, exchange, target_buy_price, target_sell_price) VALUES (?, ?, ?, ?, ?)",
        (theme_id, ticker, exchange, target_buy, target_sell)
    )
    db.commit()


def add_theme_milestone(theme_id, event_date, description):
    """为主题添加时间线节点"""
    db = get_db()
    db.execute(
        "INSERT INTO theme_milestones (theme_id, event_date, description) VALUES (?, ?, ?)",
        (theme_id, event_date, description)
    )
    db.commit()