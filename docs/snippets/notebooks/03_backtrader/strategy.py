class FixedFeePerOrder(backtrader.CommInfoBase):
    """A flat fee per execution, whatever the size or price."""

    params = (
        ("stocklike", True),
        ("commtype", backtrader.CommInfoBase.COMM_FIXED),
        ("commission", float(ts.FEE)),
    )

    def _getcommission(self, size, price, pseudoexec):
        return float(ts.FEE)


class MovingAverageCross(backtrader.Strategy):
    """Long while SMA20 > SMA50, short in the scheduled window, else flat."""

    params = (("peek", 0),)  # peek=1 is the look-ahead bug

    def __init__(self) -> None:
        self.fast = backtrader.indicators.SMA(self.data.close, period=ts.FAST)
        self.slow = backtrader.indicators.SMA(self.data.close, period=ts.SLOW)

    def _signal(self, ago: int) -> int:
        session = pd.Timestamp(self.data.datetime.date(ago))
        if ts.SHORT_FIRST_SIGNAL_SESSION <= session <= ts.SHORT_LAST_SIGNAL_SESSION:
            return -1
        return 1 if self.fast[ago] > self.slow[ago] else 0

    def prenext(self) -> None:
        self.next()

    def next(self) -> None:
        peeking = self.p.peek and len(self.data) < self.data.buflen()
        signal = self._signal(self.p.peek if peeking else 0)
        self.order_target_size(
            target=signal * ts.QUANTITY, exectype=backtrader.Order.Close
        )


def run_backtrader(peek: int = 0):
    local = prices.copy()
    local.index = local.index.tz_convert(ts.EXCHANGE_TIMEZONE).tz_localize(None)
    cerebro = backtrader.Cerebro(stdstats=False)
    cerebro.broker.setcash(float(ts.INITIAL_CASH))
    cerebro.broker.addcommissioninfo(FixedFeePerOrder())
    cerebro.adddata(
        backtrader.feeds.PandasData(dataname=local, openinterest=None),
        name=ts.INSTRUMENT,
    )
    cerebro.addstrategy(MovingAverageCross, peek=peek)
    cerebro.addanalyzer(
        create_backtrader_audit_analyzer(source_timezone=ts.EXCHANGE_TIMEZONE),
        _name="integrity",
    )
    return cerebro.run()[0]


strategy = run_backtrader()
print("final value:", strategy.broker.getvalue())
