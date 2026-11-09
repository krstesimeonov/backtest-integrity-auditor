def run_vectorbt(lag: int) -> vbt.Portfolio:
    """The toy strategy the vectorbt way; lag=0 is the look-ahead bug."""
    close = prices["close"]
    fast = vbt.MA.run(close, window=ts.FAST).ma.to_numpy()
    slow = vbt.MA.run(close, window=ts.SLOW).ma.to_numpy()
    long_signal = pd.Series((fast > slow).astype(int), index=close.index)
    sessions = (
        close.index.tz_convert(ts.EXCHANGE_TIMEZONE).normalize().tz_localize(None)
    )
    signal = long_signal.where(~ts.in_short_window(sessions), -1)
    target = signal.shift(lag).fillna(0) * ts.QUANTITY  # shares held at each close
    return vbt.Portfolio.from_orders(
        close,
        size=target,
        size_type="targetamount",
        fixed_fees=float(ts.FEE),
        init_cash=float(ts.INITIAL_CASH),
        freq="1D",
    )


portfolio = run_vectorbt(lag=1)
print("final value:", portfolio.final_value())
