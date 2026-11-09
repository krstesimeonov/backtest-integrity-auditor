class MovingAverageCross(bt.Algo):
    """Holds 100 x signal shares; the signal is lagged `lag` bars."""

    def __init__(self, lag: int) -> None:
        super().__init__()
        self.lag = lag

    def __call__(self, target) -> bool:
        closes = target.universe[ts.INSTRUMENT].dropna()
        if len(closes) <= self.lag:
            return True
        seen = closes.iloc[: len(closes) - self.lag]
        fast = seen.rolling(ts.FAST).mean().iloc[-1]
        slow = seen.rolling(ts.SLOW).mean().iloc[-1]
        signal = 1 if fast > slow else 0
        session = (
            seen.index[-1]
            .tz_convert(ts.EXCHANGE_TIMEZONE)
            .normalize()
            .tz_localize(None)
        )
        if ts.SHORT_FIRST_SIGNAL_SESSION <= session <= ts.SHORT_LAST_SIGNAL_SESSION:
            signal = -1
        wanted = ts.QUANTITY * signal
        held = (
            target.children[ts.INSTRUMENT].position
            if ts.INSTRUMENT in target.children
            else 0.0
        )
        if wanted != held:
            target.transact(wanted - held, child=ts.INSTRUMENT)
        return True


def run_bt(lag: int) -> bt.backtest.Result:
    data = prices[["close"]].rename(columns={"close": ts.INSTRUMENT})
    strategy = bt.Strategy(
        "ma_cross", [MovingAverageCross(lag)], children=[ts.INSTRUMENT]
    )
    backtest = bt.Backtest(
        strategy,
        data,
        initial_capital=float(ts.INITIAL_CASH),
        commissions=lambda quantity, price: float(ts.FEE),
        integer_positions=True,
        progress_bar=False,
    )
    return bt.run(backtest)


result = run_bt(lag=1)
print("final value:", result.backtests["ma_cross"].strategy.values.iloc[-1])
