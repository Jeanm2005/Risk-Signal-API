"""
Unit tests for the pure statistical helpers in analysis.news_vol_panel.
"""
import numpy as np
import pandas as pd
import pytest

from analysis.news_vol_panel import _spear, _per_company


def test_spear_perfect_monotonic():
    x = list(range(10))
    r, p, n = _spear(x, x)
    assert r == pytest.approx(1.0)
    assert n == 10


def test_spear_perfect_inverse():
    x = list(range(10))
    r, p, n = _spear(x, x[::-1])
    assert r == pytest.approx(-1.0)


def test_spear_too_few_points_is_nan():
    r, p, n = _spear([1, 2], [1, 2])   
    assert np.isnan(r)
    assert n == 2


def test_spear_handles_short_input_gracefully():
    r, p, n = _spear([1.0], [1.0])
    assert np.isnan(r)


def _company_frame(ticker, xs, ys):
    return pd.DataFrame({"ticker": ticker, "x": xs, "y": ys})


def test_per_company_requires_min_observations():
    small = _company_frame("AAA", list(range(5)), list(range(5)))
    med, frac_pos, ncomp = _per_company(small, "x", "y")
    assert ncomp == 0
    assert np.isnan(med)


def test_per_company_aggregates_median_and_fraction_positive():
    n = 10
    pos = _company_frame("POS", list(range(n)), list(range(n)))               
    neg = _company_frame("NEG", list(range(n)), list(range(n))[::-1])         
    df = pd.concat([pos, neg], ignore_index=True)
    med, frac_pos, ncomp = _per_company(df, "x", "y")
    assert ncomp == 2
    assert frac_pos == 0.5            
    assert med == 0.0                 


def test_per_company_all_positive_fraction():
    n = 12
    frames = [_company_frame(f"C{i}", list(range(n)), list(range(n))) for i in range(3)]
    df = pd.concat(frames, ignore_index=True)
    med, frac_pos, ncomp = _per_company(df, "x", "y")
    assert ncomp == 3
    assert frac_pos == 1.0
    assert med == 1.0