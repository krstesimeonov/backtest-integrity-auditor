"""JSON Schema (draft 2020-12) of ``edge-audit-report/1.1``.

Kept as a Python dict so the installed package needs no data files; the
tests validate every generated report against it and check that
``docs/edge_audit/edge-audit-report-1.1.schema.json`` is this dict, verbatim.
Any field added to or removed from the report must change this schema (every
object is closed with ``additionalProperties: false``).
"""

from __future__ import annotations

from typing import Any

NUMBER = {"type": "number"}
NULLABLE_NUMBER = {"type": ["number", "null"]}
NULLABLE_INTEGER = {"type": ["integer", "null"]}
NULLABLE_STRING = {"type": ["string", "null"]}
STRING = {"type": "string"}
INTEGER = {"type": "integer"}
BOOLEAN = {"type": "boolean"}


def _closed(properties: dict[str, Any], *, nullable: bool = False) -> dict[str, Any]:
    return {
        "type": ["object", "null"] if nullable else "object",
        "additionalProperties": False,
        "required": sorted(properties),
        "properties": properties,
    }


INTERVAL = _closed(
    {
        "point": NULLABLE_NUMBER,
        "lower": NULLABLE_NUMBER,
        "upper": NULLABLE_NUMBER,
        "confidence_level": NUMBER,
        "standard_error": NULLABLE_NUMBER,
        "replications": INTEGER,
        "valid_replications": INTEGER,
        "upper_unbounded": BOOLEAN,
        "point_unbounded": BOOLEAN,
    }
)
VERDICTS = {"enum": ["evidence_of_edge", "no_evidence_of_edge", "insufficient_data"]}

TERCILE_SPLIT = _closed(
    {
        "variable": STRING,
        "source": STRING,
        "status": {"enum": ["computed", "unavailable"]},
        "reason": NULLABLE_STRING,
        "trades_with_value": INTEGER,
        "rows": {
            "type": "array",
            "maxItems": 3,
            "items": _closed(
                {
                    "label": STRING,
                    "count": INTEGER,
                    "variable_min": NUMBER,
                    "variable_max": NUMBER,
                    "expectancy": INTERVAL,
                    "win_rate": NUMBER,
                }
            ),
        },
        "between_tercile_sum_of_squares": NULLABLE_NUMBER,
        "permutation_draws": INTEGER,
        "permutation_p_value": NULLABLE_NUMBER,
        "top_minus_bottom": NULLABLE_NUMBER,
    }
)

REPORT_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "edge-audit-report/1.1",
    "title": "V4 Edge Audit report",
    **_closed(
        {
            "schema": {"const": "edge-audit-report/1.1"},
            "generated_by": _closed(
                {"package": STRING, "version": STRING, "component": STRING}
            ),
            "input": _closed(
                {
                    "trades": _closed(
                        {
                            "file": STRING,
                            "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                            "schema": {"const": "edge-audit-trades/1.0"},
                            "schema_declared_in_file": BOOLEAN,
                            "rows": INTEGER,
                        }
                    ),
                    "prices": _closed(
                        {
                            "file": STRING,
                            "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                            "schema": {"const": "edge-audit-prices/1.0"},
                        },
                        nullable=True,
                    ),
                }
            ),
            "settings": _closed(
                {
                    "declared_trials": INTEGER,
                    "confidence_level": NUMBER,
                    "bootstrap_replications": INTEGER,
                    "mean_block_length": INTEGER,
                    "seed": INTEGER,
                    "trial_sharpe_std": NULLABLE_NUMBER,
                    "timing_mode": {"enum": ["day", "holding"]},
                    "day_timezone": STRING,
                    "timing_draws": INTEGER,
                    "permutation_draws": INTEGER,
                    "volatility_lookback_bars": INTEGER,
                    "cost_grid_bps": {"type": "array", "items": NUMBER},
                    "reference_trades": NULLABLE_INTEGER,
                    "decay_shift_sigma": NULLABLE_NUMBER,
                    "decay_false_alarm_probability": NUMBER,
                    "decay_horizon": INTEGER,
                    "rolling_window": NULLABLE_INTEGER,
                }
            ),
            "verdict": _closed(
                {
                    "edge": VERDICTS,
                    "reason": STRING,
                    "test": STRING,
                    "dsr": NULLABLE_NUMBER,
                    "declared_trials": INTEGER,
                    "confidence_level": NUMBER,
                }
            ),
            "answers": _closed(
                {
                    "is_there_evidence_of_an_edge": STRING,
                    "where_does_it_come_from": STRING,
                    "is_it_decaying": STRING,
                    "how_sensitive_to_costs": STRING,
                }
            ),
            "performance": _closed(
                {
                    "trade_count": INTEGER,
                    "winning_trades": INTEGER,
                    "losing_trades": INTEGER,
                    "flat_trades": INTEGER,
                    "total_net_pnl": NUMBER,
                    "total_gross_pnl": NUMBER,
                    "total_fees": NUMBER,
                    "expectancy": INTERVAL,
                    "profit_factor": INTERVAL,
                    "win_rate": INTERVAL,
                    "average_win": NULLABLE_NUMBER,
                    "average_loss": NULLABLE_NUMBER,
                    "payoff_ratio": NULLABLE_NUMBER,
                    "mean_net_return_bps": NUMBER,
                    "median_holding_hours": NUMBER,
                    "first_entry": STRING,
                    "last_exit": STRING,
                    "span_years": NUMBER,
                    "instruments": {"type": "array", "items": STRING},
                    "currency": NULLABLE_STRING,
                    "max_concurrent_trades": INTEGER,
                    "serial_dependence_p_value": NULLABLE_NUMBER,
                    "lag_one_autocorrelation": NULLABLE_NUMBER,
                }
            ),
            "luck_vs_skill": _closed(
                {
                    "trade_count": INTEGER,
                    "span_years": NUMBER,
                    "trades_per_year": NUMBER,
                    "periods_per_year": INTEGER,
                    "mean": NUMBER,
                    "standard_deviation": NULLABLE_NUMBER,
                    "sharpe_per_trade": NULLABLE_NUMBER,
                    "t_statistic": NULLABLE_NUMBER,
                    "t_p_value_one_sided": NULLABLE_NUMBER,
                    "annualized_sharpe": NULLABLE_NUMBER,
                    "sample_skewness": NULLABLE_NUMBER,
                    "sample_pearson_kurtosis": NULLABLE_NUMBER,
                    "sharpe_variance_adjustment": NULLABLE_NUMBER,
                    "sharpe_standard_error": NULLABLE_NUMBER,
                    "null_standard_error": NULLABLE_NUMBER,
                    "psr_vs_zero": NULLABLE_NUMBER,
                    "declared_trials": INTEGER,
                    "trial_sharpe_std": NULLABLE_NUMBER,
                    "trial_sharpe_std_source": {"enum": ["null_default", "declared"]},
                    "expected_max_standard_normal": NULLABLE_NUMBER,
                    "expected_max_sharpe_per_trade": NULLABLE_NUMBER,
                    "dsr": NULLABLE_NUMBER,
                    "dsr_test_statistic": NULLABLE_NUMBER,
                    "dsr_plug_in": NULLABLE_NUMBER,
                    "confidence_level": NUMBER,
                    "min_track_record_trades": NULLABLE_INTEGER,
                    "deflated_min_track_record_trades": NULLABLE_INTEGER,
                    "verdict": VERDICTS,
                    "verdict_reason": STRING,
                }
            ),
            "timing": _closed(
                {
                    "status": {"enum": ["computed", "unavailable"]},
                    "reason": NULLABLE_STRING,
                    "mode": {"enum": ["day", "holding"]},
                    "day_timezone": STRING,
                    "covered_trades": INTEGER,
                    "excluded": {
                        "type": "object",
                        "additionalProperties": INTEGER,
                    },
                    "gross_pnl_covered": NUMBER,
                    "draws": INTEGER,
                    "significance_level": NUMBER,
                    "components": {
                        "type": "array",
                        "items": _closed(
                            {
                                "name": {
                                    "enum": [
                                        "holding",
                                        "entry_timing",
                                        "exit_timing",
                                        "execution",
                                    ]
                                },
                                "total": NUMBER,
                                "share_of_gross": NULLABLE_NUMBER,
                                "mean_per_trade": INTERVAL,
                                "p_value_positive": NULLABLE_NUMBER,
                                "p_value_negative": NULLABLE_NUMBER,
                                "test": STRING,
                                "finding": STRING,
                            }
                        ),
                    },
                    "counterfactual_quantiles": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "object",
                            "additionalProperties": NUMBER,
                        },
                    },
                }
            ),
            "conditional": _closed(
                {"holding_period": TERCILE_SPLIT, "volatility_regime": TERCILE_SPLIT}
            ),
            "costs": _closed(
                {
                    "unit": STRING,
                    "mean_notional": NUMBER,
                    "fees_paid_bps": NUMBER,
                    "break_even_added_cost_bps": INTERVAL,
                    "gross_break_even_cost_bps": NUMBER,
                    "evidence_lost_at_added_cost_bps": NULLABLE_NUMBER,
                    "evidence_note": STRING,
                    "curve": {
                        "type": "array",
                        "minItems": 1,
                        "items": _closed(
                            {
                                "added_cost_bps": NUMBER,
                                "expectancy": NUMBER,
                                "expectancy_lower": NULLABLE_NUMBER,
                                "expectancy_upper": NULLABLE_NUMBER,
                                "dsr": NULLABLE_NUMBER,
                                "verdict": VERDICTS,
                            }
                        ),
                    },
                }
            ),
            "decay": _closed(
                {
                    "status": {
                        "enum": ["computed", "no_reference_edge", "unavailable"]
                    },
                    "reason": NULLABLE_STRING,
                    "trade_count": INTEGER,
                    "reference_trades": INTEGER,
                    "monitored_trades": INTEGER,
                    "reference_mean": NULLABLE_NUMBER,
                    "reference_std": NULLABLE_NUMBER,
                    "reference_sharpe": NULLABLE_NUMBER,
                    "shift_sigma": NULLABLE_NUMBER,
                    "shift_source": {"enum": ["declared", "reference_sharpe"]},
                    "false_alarm_probability": NUMBER,
                    "horizon_requested": INTEGER,
                    "horizon": INTEGER,
                    "calibration_null": {"enum": ["iid_normal"]},
                    "calibration_table": STRING,
                    "rolling_window": INTEGER,
                    "rolling_expectancy": {"type": "array", "items": NUMBER},
                    "monitored_minus_reference": {
                        "anyOf": [INTERVAL, {"type": "null"}]
                    },
                    "detectors": {
                        "type": "array",
                        "items": _closed(
                            {
                                "name": {
                                    "enum": [
                                        "rolling_expectancy",
                                        "cusum",
                                        "page_hinkley",
                                        "mixture_sprt",
                                    ]
                                },
                                "status": {"enum": ["computed", "unavailable"]},
                                "reason": NULLABLE_STRING,
                                "threshold": NULLABLE_NUMBER,
                                "parameters": {
                                    "type": "object",
                                    "additionalProperties": NUMBER,
                                },
                                "false_alarm_probability": NUMBER,
                                "horizon": INTEGER,
                                "calibration_null": {"enum": ["iid_normal"]},
                                "false_alarm_probability_over_monitored": NULLABLE_NUMBER,
                                "alarm_trade_number": NULLABLE_INTEGER,
                                "alarm_exit_time": NULLABLE_STRING,
                                "statistic_at_alarm": NULLABLE_NUMBER,
                                "max_statistic": NULLABLE_NUMBER,
                                "extra": {
                                    "type": "object",
                                    "additionalProperties": NUMBER,
                                },
                            }
                        ),
                    },
                }
            ),
            "sizing": _closed(
                {
                    "mean_notional": NUMBER,
                    "notional_cv": NUMBER,
                    "size_return_correlation": NULLABLE_NUMBER,
                    "actual_expectancy": INTERVAL,
                    "fixed_size_expectancy": INTERVAL,
                    "sizing_contribution_per_trade": INTERVAL,
                    "sizing_contribution_total": NUMBER,
                    "permutation_draws": INTEGER,
                    "permutation_p_value": NUMBER,
                    "fixed_size_dsr": NULLABLE_NUMBER,
                    "fixed_size_verdict": VERDICTS,
                    "finding": STRING,
                }
            ),
            "warnings": {"type": "array", "items": STRING},
        }
    ),
}
