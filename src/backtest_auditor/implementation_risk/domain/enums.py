"""Stable V1.5 vocabulary for reconciliation and canonical artifacts."""

from enum import StrEnum


class ComparisonLevel(StrEnum):
    """An independently available layer of cross-engine evidence.

    The definition order is the canonical serialization and reporting order.
    A later level is not evidence that an earlier level was available or
    equivalent.  For example, matching returns do not prove matching fills.
    """

    STRATEGY_SPECIFICATION = "strategy_specification"
    MARKET_DATA = "market_data"
    SIGNAL = "signal"
    ORDER = "order"
    FILL = "fill"
    TRADE = "trade"
    POSITION = "position"
    CASH = "cash"
    COST = "cost"
    EQUITY = "equity"
    RETURN = "return"


class LevelEligibilityStatus(StrEnum):
    """Whether a reference/candidate pair can compare one requested level."""

    ELIGIBLE = "eligible"
    REFERENCE_UNAVAILABLE = "reference_unavailable"
    CANDIDATE_UNAVAILABLE = "candidate_unavailable"
    BOTH_UNAVAILABLE = "both_unavailable"


class AssetClass(StrEnum):
    EQUITY = "equity"
    ETF = "etf"
    FUTURE = "future"
    OPTION = "option"
    FOREX = "forex"
    CRYPTO = "crypto"
    BOND = "bond"
    FUND = "fund"
    INDEX = "index"
    CASH = "cash"
    OTHER = "other"


class SignalType(StrEnum):
    TARGET_QUANTITY = "target_quantity"
    TARGET_WEIGHT = "target_weight"
    TARGET_NOTIONAL = "target_notional"
    SCORE = "score"
    ENTRY = "entry"
    EXIT = "exit"
    CUSTOM = "custom"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    MARKET_ON_CLOSE = "market_on_close"
    LIMIT_ON_CLOSE = "limit_on_close"
    CUSTOM = "custom"


class TimeInForce(StrEnum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"
    GTD = "gtd"
    AT_OPEN = "at_open"
    AT_CLOSE = "at_close"
    CUSTOM = "custom"


class OrderStatus(StrEnum):
    CREATED = "created"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class LiquidityRole(StrEnum):
    MAKER = "maker"
    TAKER = "taker"
    UNKNOWN = "unknown"


class TradeDirection(StrEnum):
    LONG = "long"
    SHORT = "short"


class CashMovementType(StrEnum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    DIVIDEND = "dividend"
    INTEREST = "interest"
    BORROW_FEE = "borrow_fee"
    TAX = "tax"
    SETTLEMENT = "settlement"
    TRANSFER = "transfer"
    OTHER = "other"


class CostType(StrEnum):
    COMMISSION = "commission"
    EXCHANGE_FEE = "exchange_fee"
    REGULATORY_FEE = "regulatory_fee"
    SPREAD = "spread"
    SLIPPAGE = "slippage"
    MARKET_IMPACT = "market_impact"
    BORROW = "borrow"
    TAX = "tax"
    OTHER = "other"


class ArtifactReturnConvention(StrEnum):
    SIMPLE = "simple"
    LOG = "log"
