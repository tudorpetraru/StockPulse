"""
Chart service – builds Plotly JSON specs for ticker price charts
and prediction consensus charts.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Plotly colour tokens (match design-system spec)
# ---------------------------------------------------------------------------
_NAVY = "#1B2A4A"
_BLUE = "#1976D2"
_RED = "#C62828"
_GREEN = "#2E7D32"
_AMBER = "#F57F17"
_PURPLE = "#7B1FA2"
_GRAY_VOLUME = "rgba(189,189,189,0.50)"
_GRID = "#EEEEEE"
_BG = "#FFFFFF"

_PERIOD_MAP: dict[str, str] = {
    "1M": "1mo",
    "3M": "3mo",
    "6M": "6mo",
    "1Y": "1y",
    "5Y": "5y",
}

_PORTFOLIO_COLORS = [
    _NAVY,
    _BLUE,
    _GREEN,
    _AMBER,
    _RED,
    _PURPLE,
    "#757575",
    "#9E9E9E",
    "#BDBDBD",
]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_price_chart(
    history: list[dict[str, Any]],
    symbol: str,
    period: str = "1Y",
    sma50: list[float | None] | None = None,
    sma200: list[float | None] | None = None,
) -> dict[str, Any]:
    """Return a Plotly JSON spec for an OHLCV + SMA chart.

    *history* is a list of dicts with keys:
        date (str ISO), open, high, low, close, volume
    """
    if not history:
        return _empty_chart("No price data available")

    dates = [h["date"] for h in history]
    closes = [h["close"] for h in history]
    volumes = [h.get("volume", 0) for h in history]

    traces: list[dict[str, Any]] = []

    # Price line
    traces.append(
        {
            "x": dates,
            "y": closes,
            "type": "scatter",
            "mode": "lines",
            "name": symbol,
            "line": {"color": _NAVY, "width": 2},
            "hovertemplate": "%{x}<br>$%{y:.2f}<extra></extra>",
        }
    )

    # SMA 50
    if sma50:
        traces.append(
            {
                "x": dates,
                "y": sma50,
                "type": "scatter",
                "mode": "lines",
                "name": "SMA 50",
                "line": {"color": _BLUE, "width": 1, "dash": "dot"},
            }
        )

    # SMA 200
    if sma200:
        traces.append(
            {
                "x": dates,
                "y": sma200,
                "type": "scatter",
                "mode": "lines",
                "name": "SMA 200",
                "line": {"color": _RED, "width": 1, "dash": "dot"},
            }
        )

    # Volume bars on secondary y-axis
    traces.append(
        {
            "x": dates,
            "y": volumes,
            "type": "bar",
            "name": "Volume",
            "yaxis": "y2",
            "marker": {"color": _GRAY_VOLUME},
            "hovertemplate": "%{x}<br>Vol: %{y:,.0f}<extra></extra>",
        }
    )

    layout = _base_layout(f"{symbol} — {period}")
    layout.update(
        {
            "yaxis": {"title": "Price ($)", "gridcolor": _GRID, "side": "left"},
            "yaxis2": {
                "title": "Volume",
                "overlaying": "y",
                "side": "right",
                "showgrid": False,
                "range": [0, max(volumes or [1]) * 4],  # keep bars short
            },
        }
    )

    return {"data": traces, "layout": layout}


def build_consensus_chart(
    actual_prices: list[dict[str, Any]],
    consensus_snapshots: list[dict[str, Any]],
    symbol: str,
    period: str = "2Y",
) -> dict[str, Any]:
    """Return a Plotly JSON spec for consensus-target-band vs actual price.

    *actual_prices*: [{date, close}, ...]
    *consensus_snapshots*: [{date, avg_target, low_target, high_target,
                             resolved (bool), accurate (bool|None)}, ...]
    """
    if not actual_prices:
        return _empty_chart("No price data available for consensus chart")

    # Actual price line
    traces: list[dict[str, Any]] = [
        {
            "x": [p["date"] for p in actual_prices],
            "y": [p["close"] for p in actual_prices],
            "type": "scatter",
            "mode": "lines",
            "name": "Actual Price",
            "line": {"color": _BLUE, "width": 2},
        }
    ]

    if consensus_snapshots:
        cs_dates = [s["date"] for s in consensus_snapshots]
        cs_avg = [s["avg_target"] for s in consensus_snapshots]
        cs_low = [s["low_target"] for s in consensus_snapshots]
        cs_high = [s["high_target"] for s in consensus_snapshots]

        # Shaded band (low → high)
        traces.append(
            {
                "x": cs_dates + cs_dates[::-1],
                "y": cs_high + cs_low[::-1],
                "type": "scatter",
                "fill": "toself",
                "fillcolor": "rgba(46,125,50,0.10)",
                "line": {"color": "rgba(0,0,0,0)"},
                "name": "Target Range",
                "showlegend": True,
                "hoverinfo": "skip",
            }
        )

        # Average consensus dashed line
        traces.append(
            {
                "x": cs_dates,
                "y": cs_avg,
                "type": "scatter",
                "mode": "lines",
                "name": "Avg Consensus Target",
                "line": {"color": _AMBER, "width": 2, "dash": "dash"},
            }
        )

        # Resolution markers
        resolved = [s for s in consensus_snapshots if s.get("resolved")]
        if resolved:
            accurate = [s for s in resolved if s.get("accurate")]
            missed = [s for s in resolved if not s.get("accurate")]
            if accurate:
                traces.append(
                    {
                        "x": [s["date"] for s in accurate],
                        "y": [s["avg_target"] for s in accurate],
                        "type": "scatter",
                        "mode": "markers",
                        "name": "✓ Accurate",
                        "marker": {"color": _GREEN, "size": 10, "symbol": "circle"},
                    }
                )
            if missed:
                traces.append(
                    {
                        "x": [s["date"] for s in missed],
                        "y": [s["avg_target"] for s in missed],
                        "type": "scatter",
                        "mode": "markers",
                        "name": "✗ Missed",
                        "marker": {"color": _RED, "size": 10, "symbol": "x"},
                    }
                )

    layout = _base_layout(f"{symbol} — Consensus vs Actual ({period})")
    return {"data": traces, "layout": layout}


def build_portfolio_sector_chart(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a donut chart for portfolio sector allocation."""
    if not points:
        return _empty_chart("No sector data available")

    labels = [str(point["label"]) for point in points]
    values = [float(point["value"]) for point in points]
    return {
        "data": [
            {
                "type": "pie",
                "labels": labels,
                "values": values,
                "hole": 0.45,
                "sort": False,
                "direction": "clockwise",
                "marker": {"colors": _PORTFOLIO_COLORS[: len(labels)]},
                "textinfo": "label+percent",
            }
        ],
        "layout": {
            "plot_bgcolor": _BG,
            "paper_bgcolor": _BG,
            "margin": {"l": 10, "r": 10, "t": 20, "b": 20},
            "showlegend": False,
        },
    }


def build_portfolio_positions_chart(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a readable holdings chart (top positions + optional Other bucket)."""
    if not points:
        return _empty_chart("No position data available")

    ranked = sorted(
        (
            {"label": str(point["label"]), "value": float(point["value"])}
            for point in points
            if float(point.get("value") or 0.0) > 0
        ),
        key=lambda point: point["value"],
        reverse=True,
    )
    if not ranked:
        return _empty_chart("No position data available")

    top_n = 12
    display_points = ranked
    if len(ranked) > top_n:
        head = ranked[: top_n - 1]
        other_value = sum(point["value"] for point in ranked[top_n - 1 :])
        if other_value > 0:
            head.append({"label": "Other", "value": other_value})
        display_points = head

    labels = [point["label"] for point in display_points]
    values = [point["value"] for point in display_points]
    total = sum(values)
    percentages = [(value / total * 100.0) if total > 0 else 0.0 for value in values]
    colors = [_PORTFOLIO_COLORS[idx % len(_PORTFOLIO_COLORS)] for idx in range(len(labels))]
    if labels and labels[-1] == "Other":
        colors[-1] = "#B0BEC5"

    return {
        "data": [
            {
                "type": "bar",
                "orientation": "h",
                "x": values,
                "y": labels,
                "text": [f"{pct:.1f}%" for pct in percentages],
                "textposition": "auto",
                "customdata": percentages,
                "marker": {"color": colors},
                "hovertemplate": "%{y}<br>$%{x:,.0f}<br>%{customdata:.1f}% of portfolio<extra></extra>",
            }
        ],
        "layout": {
            "plot_bgcolor": _BG,
            "paper_bgcolor": _BG,
            "margin": {"l": 95, "r": 12, "t": 20, "b": 40},
            "xaxis": {"title": "Value ($)", "gridcolor": _GRID, "tickprefix": "$", "separatethousands": True},
            "yaxis": {"title": "", "autorange": "reversed", "automargin": True},
            "showlegend": False,
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_layout(title: str) -> dict[str, Any]:
    return {
        "title": {"text": title, "font": {"size": 14, "color": _NAVY}},
        "plot_bgcolor": _BG,
        "paper_bgcolor": _BG,
        "xaxis": {"gridcolor": _GRID, "showgrid": True},
        "yaxis": {"gridcolor": _GRID},
        "legend": {"orientation": "h", "y": -0.15},
        "margin": {"l": 50, "r": 50, "t": 40, "b": 60},
        "hovermode": "x unified",
    }


def _empty_chart(message: str) -> dict[str, Any]:
    return {
        "data": [],
        "layout": {
            "xaxis": {"visible": False},
            "yaxis": {"visible": False},
            "annotations": [
                {
                    "text": message,
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.5,
                    "y": 0.5,
                    "showarrow": False,
                    "font": {"size": 16, "color": "#9E9E9E"},
                }
            ],
            "plot_bgcolor": _BG,
            "paper_bgcolor": _BG,
        },
    }


def yfinance_period(ui_period: str) -> str:
    """Map a UI period label (1M, 3M, …) to a yfinance period string."""
    return _PERIOD_MAP.get(ui_period, "1y")
