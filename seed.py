"""生成演示数据：3 个资产账户、2 个负债账户及过去 12 个月月度快照。

用法：
    python seed.py
（需先通过应用完成数据库配置，config.ini 已存在。）
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.config import AppConfig
from app.db.engine import db
from app.db.migrate import run_migrations
from app.db.models import Account, SIDE_ASSET, SIDE_LIABILITY
from app.services import snapshots as snapshot_service
from app.utils.dates import add_months, month_end

ACCOUNTS = [
    {
        "name": "自住房产",
        "side": SIDE_ASSET,
        "category": "fixed_asset",
        "note": "按市场价保守估算",
    },
    {
        "name": "招商银行活期",
        "side": SIDE_ASSET,
        "category": "cash",
        "note": "日常备用金",
    },
    {
        "name": "沪深300指数基金",
        "side": SIDE_ASSET,
        "category": "fund",
        "note": "长期定投",
    },
    {
        "name": "住房按揭",
        "side": SIDE_LIABILITY,
        "category": "long_term_debt",
        "note": "剩余本金",
    },
    {
        "name": "信用卡待还",
        "side": SIDE_LIABILITY,
        "category": "short_term_debt",
        "note": "每月账单",
    },
]

BASE_VALUES = {
    "自住房产": Decimal("1800000"),
    "招商银行活期": Decimal("80000"),
    "沪深300指数基金": Decimal("150000"),
    "住房按揭": Decimal("900000"),
    "信用卡待还": Decimal("8000"),
}

FUND_CHANGES = [
    Decimal("0"),
    Decimal("4200"),
    Decimal("-3100"),
    Decimal("7600"),
    Decimal("2300"),
    Decimal("-1800"),
    Decimal("5400"),
    Decimal("8800"),
    Decimal("-2600"),
    Decimal("6100"),
    Decimal("9400"),
    Decimal("3200"),
]


def ensure_accounts(session) -> dict:
    result = {}
    for spec in ACCOUNTS:
        account = session.scalar(select(Account).where(Account.name == spec["name"]))
        if account is None:
            account = Account(
                name=spec["name"],
                side=spec["side"],
                category=spec["category"],
                currency="CNY",
                note=spec["note"],
                archived=False,
            )
            session.add(account)
            session.flush()
            print(f"创建账户：{account.name}")
        else:
            print(f"账户已存在：{account.name}")
        result[account.name] = account
    session.commit()
    return result


def snapshot_dates(today: date) -> list:
    dates = []
    for offset in range(11, -1, -1):
        target = add_months(today, -offset)
        day = min(month_end(target), today)
        dates.append(day)
    return sorted(set(dates))


def value_for(name: str, index: int) -> Decimal:
    if name == "自住房产":
        return BASE_VALUES[name] + Decimal(index) * Decimal("5000")
    if name == "招商银行活期":
        return BASE_VALUES[name] + Decimal(index) * Decimal("2500")
    if name == "沪深300指数基金":
        return BASE_VALUES[name] + sum(FUND_CHANGES[: index + 1])
    if name == "住房按揭":
        return BASE_VALUES[name] - Decimal(index) * Decimal("6000")
    if name == "信用卡待还":
        return BASE_VALUES[name] + Decimal(index % 3) * Decimal("1500")
    return BASE_VALUES.get(name, Decimal("0"))


def main() -> int:
    config = AppConfig()
    if not config.has_database_config():
        print("未找到数据库配置。请先启动应用并在“数据库设置”中完成配置，再运行 seed.py。")
        return 1

    db.configure(config.db_settings())
    assert db.url is not None
    run_migrations(db.url)
    print("数据库已就绪。")

    today = date.today()
    dates = snapshot_dates(today)
    with db.session_scope() as session:
        accounts = ensure_accounts(session)
        count = 0
        for index, day in enumerate(dates):
            for name, account in accounts.items():
                snapshot_service.save_snapshot(
                    session,
                    account_id=account.id,
                    snapshot_date=day,
                    value=value_for(name, index),
                    note="seed 演示数据",
                    overwrite=True,
                )
                count += 1
        print(f"已写入 {len(dates)} 个月份、{count} 条估值快照。")

    db.dispose()
    print("完成。启动应用即可查看仪表盘与折线图。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
