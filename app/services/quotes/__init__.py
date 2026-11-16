"""行情适配器：股票/ETF、基金、黄金白银、大宗商品与汇率。"""
from app.services.quotes.base import HTTP_TIMEOUT, PricePoint, QuoteError
from app.services.quotes.commodity import (
    COMMODITY_ALIASES,
    COMMODITY_LABELS,
    COMMODITY_UNITS,
    copper_cents_to_cny_ton,
    fetch_commodity,
    normalize_commodity,
    parse_domestic_futures,
    parse_sina_futures,
)
from app.services.quotes.fund import fetch_fund_nav, parse_fund_payload
from app.services.quotes.fx import fetch_rate, refresh_rates, usd_cny
from app.services.quotes.gold import (
    GOLD_ALIASES,
    SILVER_ALIASES,
    fetch_gold,
    fetch_silver,
    parse_gold_api,
    parse_sina_spot,
)
from app.services.quotes.provider import (
    clear_cache,
    get_price,
    resolve_market,
)
from app.services.quotes.stock import (
    MARKET_CURRENCY,
    Quote,
    QuoteRefreshResult,
    fetch_quote,
    latest_quotes,
    normalize_symbol,
    refresh_stock_quotes,
    save_quote,
)

__all__ = [
    "COMMODITY_ALIASES",
    "COMMODITY_LABELS",
    "COMMODITY_UNITS",
    "GOLD_ALIASES",
    "HTTP_TIMEOUT",
    "MARKET_CURRENCY",
    "PricePoint",
    "Quote",
    "QuoteError",
    "QuoteRefreshResult",
    "SILVER_ALIASES",
    "clear_cache",
    "copper_cents_to_cny_ton",
    "fetch_commodity",
    "fetch_fund_nav",
    "fetch_gold",
    "fetch_quote",
    "fetch_rate",
    "fetch_silver",
    "get_price",
    "latest_quotes",
    "normalize_commodity",
    "normalize_symbol",
    "parse_domestic_futures",
    "parse_fund_payload",
    "parse_gold_api",
    "parse_sina_futures",
    "parse_sina_spot",
    "refresh_rates",
    "refresh_stock_quotes",
    "resolve_market",
    "save_quote",
    "usd_cny",
]
