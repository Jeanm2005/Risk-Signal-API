"""
Unit tests for the volatility-labeling math in ml.label_volatility.
"""
import math
from datetime import date, timedelta

import numpy as np
import pytest

from ml.label_volatility import (
    realized_vol, assign_terciles, TRADING_DAYS_PER_YEAR, MIN_RETURNS)

FILED = date(2026, 1, 15)


def _days(n, start_offset=1):
    """n consecutive calendar days starting at FILED + start_offset."""
    return [FILED + timedelta(days=i) for i in range(start_offset, start_offset + n)]


def test_constant_prices_give_zero_vol():
    n_prices = MIN_RETURNS + 2               # enough to clear the returns floor
    dates = _days(n_prices)
    result = realized_vol(dates, [100.0] * n_prices, FILED)
    assert result["realized_vol"] == 0.0
    assert result["n_returns"] == n_prices - 1


def test_too_few_returns_returns_none():
    # 3 prices -> 2 returns, below the default min_returns floor -> None.
    dates = _days(3)
    result = realized_vol(dates, [100.0, 101.0, 102.0], FILED)
    assert result["realized_vol"] is None
    assert result["window_start"] is None
    assert result["n_returns"] == 2


def test_filing_day_gap_is_excluded():
    # A price stamped ON filed_date must be dropped; the window opens strictly at t+1.
    n = MIN_RETURNS + 2
    dates = [FILED] + _days(n)
    closes = [999.0] + [100.0] * n           # the filing-day 999 must not enter
    result = realized_vol(dates, closes, FILED)
    assert result["window_start"] == _days(n)[0]    # first in-window day, not FILED
    assert result["realized_vol"] == 0.0            # 999 excluded => constant => 0


def test_annualization_matches_known_std():
    # Construct prices from known log-returns; vol must equal std(ddof=1)*sqrt(252).
    # Generate comfortably more than MIN_RETURNS returns so the floor is cleared
    # regardless of its configured value.
    a = 0.02
    n_returns = MIN_RETURNS + 3
    log_returns = np.array([a if i % 2 == 0 else -a for i in range(n_returns)])
    prices = np.exp(np.concatenate([[0.0], np.cumsum(log_returns)]))
    dates = _days(len(prices))
    result = realized_vol(dates, list(prices), FILED)
    expected = float(np.std(log_returns, ddof=1)) * math.sqrt(TRADING_DAYS_PER_YEAR)
    assert result["realized_vol"] == pytest.approx(expected, abs=1e-9)


def test_prices_past_window_end_are_excluded():
    n = MIN_RETURNS + 2
    dates = _days(n) + [FILED + timedelta(days=60)]    # last day well past the window
    closes = [100.0] * n + [500.0]                     # spike outside window ignored
    result = realized_vol(dates, closes, FILED)
    assert result["realized_vol"] == 0.0


def test_terciles_are_balanced_and_ordered():
    vols = [float(i) for i in range(1, 10)]            # 1..9
    q_low, q_high, labeler = assign_terciles(vols)
    assert q_low < q_high
    assert labeler(min(vols)) == "low"
    assert labeler(max(vols)) == "high"
    labels = [labeler(v) for v in vols]
    # Each bucket populated; balanced by construction on a uniform spread.
    assert labels.count("low") == 3
    assert labels.count("medium") == 3
    assert labels.count("high") == 3


def test_tercile_boundaries_are_inclusive_lower():
    # labeler uses <= boundaries: a value exactly on q_low is "low".
    q_low, q_high, labeler = assign_terciles([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    assert labeler(q_low) == "low"
    assert labeler(q_high) == "medium"