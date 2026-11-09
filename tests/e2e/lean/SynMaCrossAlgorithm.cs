/*
 * The W3-J12 end-to-end toy strategy (tests/e2e/strategy_spec.md) written for
 * QuantConnect LEAN. tests/e2e/lean/run_lean.py copies this file into a LEAN
 * checkout's Algorithm.CSharp project, builds it, and runs it twice:
 *
 *   lag=1  the specification: 20 minutes before the close, act on the last
 *          completed bar's signal (LEAN's own SMA indicators) with a
 *          market-on-close order, which LEAN fills at today's close;
 *   lag=0  the injected look-ahead defect: the algorithm reads today's close
 *          from the price file before the close and trades on it.
 */

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using QuantConnect.Indicators;
using QuantConnect.Orders.Fees;

namespace QuantConnect.Algorithm.CSharp
{
    public class SynMaCrossAlgorithm : QCAlgorithm
    {
        private const int FastPeriod = 20;
        private const int SlowPeriod = 50;
        private const int Quantity = 100;
        private static readonly DateTime ShortFirstSignalSession = new DateTime(2025, 2, 6);
        private static readonly DateTime ShortLastSignalSession = new DateTime(2025, 3, 5);

        private Symbol _syn;
        private SimpleMovingAverage _fast;
        private SimpleMovingAverage _slow;
        private int _lag;
        private SortedDictionary<DateTime, decimal> _peekedCloses;

        public override void Initialize()
        {
            SetStartDate(2024, 1, 2);
            SetEndDate(2025, 7, 14);
            SetCash(100000);
            _lag = int.Parse(GetParameter("lag", "1"), CultureInfo.InvariantCulture);

            var equity = AddEquity("SYN", Resolution.Daily, Market.USA, fillForward: false,
                leverage: 1m, extendedMarketHours: false,
                dataNormalizationMode: DataNormalizationMode.Raw);
            equity.SetFeeModel(new ConstantFeeModel(1m));
            _syn = equity.Symbol;
            _fast = SMA(_syn, FastPeriod, Resolution.Daily);
            _slow = SMA(_syn, SlowPeriod, Resolution.Daily);
            SetBenchmark(_ => 0m);

            if (_lag == 0)
            {
                // The defect: the whole price file is read up front.
                _peekedCloses = new SortedDictionary<DateTime, decimal>();
                var path = Path.Combine(Globals.DataFolder, GetParameter("peek-file"));
                foreach (var line in File.ReadLines(path).Skip(1))
                {
                    var cells = line.Split(',');
                    var session = DateTime.ParseExact(cells[0].Substring(0, 10), "yyyy-MM-dd",
                        CultureInfo.InvariantCulture);
                    _peekedCloses[session] = decimal.Parse(cells[4], CultureInfo.InvariantCulture);
                }
            }

            Schedule.On(DateRules.EveryDay(_syn), TimeRules.BeforeMarketClose(_syn, 20), Rebalance);
        }

        private void Rebalance()
        {
            DateTime session;
            int signal;
            if (_lag == 0)
            {
                session = Time.Date;
                var closes = _peekedCloses.Where(item => item.Key <= session).Select(item => item.Value).ToList();
                signal = closes.Count >= SlowPeriod
                    && closes.Skip(closes.Count - FastPeriod).Average() > closes.Skip(closes.Count - SlowPeriod).Average()
                    ? 1 : 0;
            }
            else
            {
                if (_fast.Samples == 0)
                {
                    return;
                }
                session = _fast.Current.EndTime.Date;
                signal = _slow.IsReady && _fast.Current.Value > _slow.Current.Value ? 1 : 0;
            }
            if (session >= ShortFirstSignalSession && session <= ShortLastSignalSession)
            {
                signal = -1;
            }
            var delta = Quantity * signal - (int)Portfolio[_syn].Quantity;
            if (delta != 0)
            {
                MarketOnCloseOrder(_syn, delta);
            }
        }
    }
}
