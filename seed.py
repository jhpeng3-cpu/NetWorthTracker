"""生成演示数据：3 个资产账户、2 个负债账户及过去 12 个月月度快照。

用法：
    python seed.py
（需先通过应用完成数据库配置，config.ini 已存在。）
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.config import AppConfig
from app.db.engine import db
from app.db.migrate import run_migrations
from app.db.models import Account, AccountItem, SIDE_ASSET, SIDE_LIABILITY
from app.services import profit
from app.services import snapshots as snapshot_service
from app.services.profit import LotInput
from app.utils.dates import add_months, month_end

ACCOUNTS = [
    {
        "name": "自住房产",
        "side": SIDE_ASSET,
        "items": [("房产", "fixed_asset")],
        "note": "按市场价保守估算",
    },
    {
        "name": "招商银行活期",
        "side": SIDE_ASSET,
        "items": [("活期存款", "cash")],
        "note": "日常备用金",
    },
    {
        "name": "证券账户",
        "side": SIDE_ASSET,
        "items": [("现金", "cash"), ("股票", "stock"), ("债券", "bond")],
        "note": "多类别子项示例",
    },
    {
        "name": "沪深300指数基金",
        "side": SIDE_ASSET,
        "items": [("指数基金", "fund")],
        "note": "长期定投",
    },
    {
        "name": "住房按揭",
        "side": SIDE_LIABILITY,
        "items": [("剩余本金", "long_term_debt")],
        "note": "剩余本金",
    },
    {
        "name": "信用卡待还",
        "side": SIDE_LIABILITY,
        "items": [("本期账单", "short_term_debt")],
        "note": "每月账单",
    },
]

BASE_VALUES = {
    "自住房产": Decimal("1800000"),
    "招商银行活期": Decimal("80000"),
    "证券账户": Decimal("300000"),
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
                currency="CNY",
                note=spec["note"],
                archived=False,
            )
            account.items = [
                AccountItem(name=name, category=category, sort_order=index)
                for index, (name, category) in enumerate(spec["items"])
            ]
            session.add(account)
            session.flush()
            print(f"创建账户：{account.name}（{len(spec['items'])} 个子项）")
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
    if name == "证券账户":
        return BASE_VALUES[name] + Decimal(index) * Decimal("8000")
    if name == "沪深300指数基金":
        return BASE_VALUES[name] + sum(FUND_CHANGES[: index + 1])
    if name == "住房按揭":
        return BASE_VALUES[name] - Decimal(index) * Decimal("6000")
    if name == "信用卡待还":
        return BASE_VALUES[name] + Decimal(index % 3) * Decimal("1500")
    return BASE_VALUES.get(name, Decimal("0"))


def ensure_lots(session, accounts: dict) -> None:
    """给部分子项写入成本批次，便于查看盈亏示例。"""
    today = date.today()
    plans = [
        (
            "证券账户",
            "股票",
            [
                LotInput(
                    trade_date=today - timedelta(days=320),
                    quantity=Decimal("400"),
                    unit_cost=Decimal("240"),
                    fee=Decimal("30"),
                    note="首次建仓",
                ),
            ],
        ),
        (
            "沪深300指数基金",
            "指数基金",
            [
                LotInput(
                    trade_date=today - timedelta(days=200),
                    quantity=Decimal("750"),
                    unit_cost=Decimal("128"),
                    fee=Decimal("0"),
                    note="定投",
                ),
            ],
        ),
    ]
    for account_name, item_name, lots in plans:
        account = accounts.get(account_name)
        if account is None:
            continue
        item = next((entry for entry in account.items if entry.name == item_name), None)
        if item is None:
            continue
        if profit.list_lots(session, item.id):
            print(f"成本批次已存在：{account_name} / {item_name}")
            continue
        profit.save_lots(session, item.id, lots)
        print(f"写入成本批次：{account_name} / {item_name}（{len(lots)} 条）")


def main() -> int:
    config = AppConfig()
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
                item_total = len(account.items)
                for item_index, item in enumerate(account.items):
                    share = value_for(name, index) / item_total
                    snapshot_service.save_snapshot(
                        session,
                        item_id=item.id,
                        snapshot_date=day,
                        value=share,
                        note="seed 演示数据",
                        overwrite=True,
                    )
                    count += 1
        print(f"已写入 {len(dates)} 个月份、{count} 条估值快照。")
        ensure_lots(session, accounts)

    db.dispose()
    print("完成。启动应用即可查看仪表盘与折线图。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
