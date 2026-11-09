VENUE = Venue("SIM")
INSTRUMENT_ID = InstrumentId(Symbol(ts.INSTRUMENT), VENUE)
BAR_TYPE = BarType.from_str(f"{INSTRUMENT_ID}-1-DAY-LAST-EXTERNAL")


class MovingAverageCrossConfig(StrategyConfig, frozen=True):
    lag: int = 1  # lag=0 is the look-ahead bug


class MovingAverageCross(Strategy):
    def __init__(self, config: MovingAverageCrossConfig) -> None:
        super().__init__(config)
        self.fast = SimpleMovingAverage(ts.FAST)
        self.slow = SimpleMovingAverage(ts.SLOW)
        self.lag = config.lag
        self.previous_signal = 0

    def on_start(self) -> None:
        self.register_indicator_for_bars(BAR_TYPE, self.fast)
        self.register_indicator_for_bars(BAR_TYPE, self.slow)
        self.subscribe_bars(BAR_TYPE)

    def on_bar(self, bar: Bar) -> None:
        ready = self.fast.initialized and self.slow.initialized
        long_signal = 1 if ready and self.fast.value > self.slow.value else 0
        session = (
            pd.Timestamp(bar.ts_event, unit="ns", tz="UTC")
            .tz_convert(ts.EXCHANGE_TIMEZONE)
            .normalize()
            .tz_localize(None)
        )
        in_short = (
            ts.SHORT_FIRST_SIGNAL_SESSION <= session <= ts.SHORT_LAST_SIGNAL_SESSION
        )
        signal = -1 if in_short else long_signal
        acting = signal if self.lag == 0 else self.previous_signal
        self.previous_signal = signal
        delta = acting * ts.QUANTITY - int(self.portfolio.net_position(INSTRUMENT_ID))
        if delta:
            self.submit_order(
                self.order_factory.market(
                    INSTRUMENT_ID,
                    OrderSide.BUY if delta > 0 else OrderSide.SELL,
                    Quantity.from_int(abs(delta)),
                    time_in_force=TimeInForce.GTC,
                )
            )


def bars() -> list[Bar]:
    return [
        Bar(
            BAR_TYPE,
            Price.from_str(f"{row.open:.2f}"),
            Price.from_str(f"{row.high:.2f}"),
            Price.from_str(f"{row.low:.2f}"),
            Price.from_str(f"{row.close:.2f}"),
            Quantity.from_int(int(row.volume)),
            timestamp.value,
            timestamp.value,
        )
        for timestamp, row in prices.iterrows()
    ]


def run_nautilus(lag: int) -> BacktestEngine:
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id=TraderId("EXAMPLE-001"),
            logging=LoggingConfig(log_level="ERROR", bypass_logging=True),
        )
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(ts.INITIAL_CASH, USD)],
        fee_model=FixedFeeModel(Money(ts.FEE, USD)),
        fill_model=FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=1),
    )
    engine.add_instrument(
        Equity(
            instrument_id=INSTRUMENT_ID,
            raw_symbol=Symbol(ts.INSTRUMENT),
            currency=USD,
            price_precision=2,
            price_increment=Price.from_str("0.01"),
            lot_size=Quantity.from_int(1),
            ts_event=0,
            ts_init=0,
        )
    )
    engine.add_data(bars())
    engine.add_strategy(MovingAverageCross(MovingAverageCrossConfig(lag=lag)))
    engine.run()
    return engine
