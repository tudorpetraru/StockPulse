from __future__ import annotations

import asyncio
import math
from datetime import date, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from app.services.providers.base import BaseProvider, DataUnavailable, InvalidSymbol


class YFinanceProvider(BaseProvider):
    async def _ticker(self, symbol: str) -> yf.Ticker:
        if not symbol or not symbol.strip():
            raise InvalidSymbol("Symbol cannot be empty")
        return yf.Ticker(symbol.upper())

    async def get_company_profile(self, symbol: str) -> dict[str, Any]:
        ticker = await self._ticker(symbol)
        info = await asyncio.to_thread(lambda: ticker.info)
        if not info:
            raise DataUnavailable(f"No company profile for {symbol}")
        return {
            "symbol": symbol.upper(),
            "name": info.get("longName") or info.get("shortName") or symbol.upper(),
            "exchange": info.get("exchange"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap": info.get("marketCap"),
            "current_price": info.get("currentPrice"),
            "day_change": info.get("regularMarketChangePercent"),
            "description": info.get("longBusinessSummary"),
        }

    async def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        ticker = await self._ticker(symbol)
        info = await asyncio.to_thread(lambda: ticker.info)
        if not info:
            raise DataUnavailable(f"No key metrics for {symbol}")
        fields = {
            "pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg": info.get("pegRatio"),
            "pb": info.get("priceToBook"),
            "ps": info.get("priceToSalesTrailing12Months"),
            "ev_ebitda": info.get("enterpriseToEbitda"),
            "profit_margin": info.get("profitMargins"),
            "roe": info.get("returnOnEquity"),
            "debt_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "beta": info.get("beta"),
            "market_cap": info.get("marketCap"),
        }
        return fields

    async def get_financials(self, symbol: str, period: str) -> dict[str, Any]:
        ticker = await self._ticker(symbol)

        def load_financials() -> dict[str, Any]:
            if period == "quarterly":
                income = ticker.quarterly_income_stmt
                balance = ticker.quarterly_balance_sheet
                cashflow = ticker.quarterly_cashflow
            else:
                income = ticker.income_stmt
                balance = ticker.balance_sheet
                cashflow = ticker.cashflow
            return {
                "income_statement": _df_to_records(income),
                "balance_sheet": _df_to_records(balance),
                "cash_flow": _df_to_records(cashflow),
            }

        result = await asyncio.to_thread(load_financials)
        if not any(result.values()):
            raise DataUnavailable(f"No financials for {symbol}")
        return result

    async def get_analyst_ratings(self, symbol: str) -> list[dict[str, Any]]:
        ticker = await self._ticker(symbol)

        def load() -> list[dict[str, Any]]:
            recs = ticker.upgrades_downgrades
            if recs is None or recs.empty:
                recs = ticker.recommendations
            if recs is None or recs.empty:
                return []
            df = recs.reset_index()
            records: list[dict[str, Any]] = []
            for row in df.to_dict(orient="records")[:100]:
                records.append(
                    {
                        "date": str(row.get("Date") or row.get("index") or row.get("date")),
                        "firm": row.get("Firm") or row.get("firm") or "Unknown",
                        "action": row.get("Action") or row.get("action"),
                        "rating": row.get("To Grade") or row.get("ToGrade") or row.get("grade") or "N/A",
                        "price_target": row.get("Price Target") or row.get("price_target"),
                    }
                )
            return records

        return await asyncio.to_thread(load)

    async def get_insider_transactions(self, symbol: str) -> list[dict[str, Any]]:
        ticker = await self._ticker(symbol)

        def load() -> list[dict[str, Any]]:
            table = ticker.insider_transactions
            if table is None or table.empty:
                return []
            return table.reset_index().to_dict(orient="records")

        return await asyncio.to_thread(load)

    async def get_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        ticker = await self._ticker(symbol)
        raw_news = await asyncio.to_thread(lambda: ticker.news or [])
        items: list[dict[str, Any]] = []
        for item in raw_news[:limit]:
            content = item.get("content", {})
            items.append(
                {
                    "title": content.get("title") or item.get("title"),
                    "source": _source_name(content.get("provider") or item.get("publisher")),
                    "published": content.get("pubDate") or item.get("providerPublishTime"),
                    "url": content.get("canonicalUrl", {}).get("url") or item.get("link"),
                    "symbol": symbol.upper(),
                }
            )
        return items

    async def get_price_history(self, symbol: str, period: str) -> list[dict[str, Any]]:
        ticker = await self._ticker(symbol)

        def load() -> list[dict[str, Any]]:
            hist = ticker.history(period=period, auto_adjust=False)
            if hist is None or hist.empty:
                return []
            hist = hist.reset_index()
            return hist.to_dict(orient="records")

        return await asyncio.to_thread(load)

    async def get_current_price(self, symbol: str) -> float:
        ticker = await self._ticker(symbol)

        def load() -> float:
            info = ticker.fast_info or {}
            price = info.get("lastPrice") or info.get("regularMarketPrice")
            if price is None:
                hist = ticker.history(period="1d")
                if hist is None or hist.empty:
                    raise DataUnavailable(f"No current price for {symbol}")
                price = float(hist["Close"].iloc[-1])
            return float(price)

        return await asyncio.to_thread(load)

    async def get_price_on_date(self, symbol: str, target_date: date) -> float | None:
        ticker = await self._ticker(symbol)

        def load() -> float | None:
            start = pd.Timestamp(target_date)
            end = pd.Timestamp(target_date + timedelta(days=5))
            hist = ticker.history(start=start, end=end, auto_adjust=True)
            if hist is None or hist.empty:
                return None
            return float(hist["Close"].iloc[0])

        return await asyncio.to_thread(load)

    async def get_consensus_targets(self, symbol: str) -> dict[str, Any]:
        ticker = await self._ticker(symbol)

        def load() -> dict[str, Any]:
            targets = ticker.analyst_price_targets
            summary = ticker.recommendations_summary
            result: dict[str, Any] = {
                "low": None,
                "avg": None,
                "median": None,
                "high": None,
                "count": None,
                "consensus": None,
                "current": None,
            }
            if isinstance(targets, dict):
                result.update(
                    {
                        "low": targets.get("low"),
                        "avg": targets.get("mean") or targets.get("avg"),
                        "median": targets.get("median"),
                        "high": targets.get("high"),
                        "count": targets.get("numberOfAnalystOpinions") or targets.get("count"),
                        "current": targets.get("current") or targets.get("currentPrice"),
                    }
                )
            if summary is not None and not getattr(summary, "empty", True):
                row = summary.iloc[0].to_dict()
                for key in ("strongBuy", "buy", "hold", "sell", "strongSell"):
                    if row.get(key):
                        result["consensus"] = key
                        break
            if result["current"] is None:
                info = ticker.fast_info or {}
                result["current"] = info.get("lastPrice")
            if result["current"] is None:
                raise DataUnavailable(f"No consensus/current price for {symbol}")
            return result

        return await asyncio.to_thread(load)

    async def get_holders(self, symbol: str) -> dict[str, list[dict[str, Any]]]:
        ticker = await self._ticker(symbol)

        def load() -> dict[str, list[dict[str, Any]]]:
            institutional_df = getattr(ticker, "institutional_holders", None)
            mutual_df = getattr(ticker, "mutualfund_holders", None)
            if mutual_df is None:
                mutual_df = getattr(ticker, "mutual_fund_holders", None)
            return {
                "institutional": _holders_df_to_records(institutional_df),
                "mutual_fund": _holders_df_to_records(mutual_df),
            }

        return await asyncio.to_thread(load)

    async def get_earnings(self, symbol: str) -> dict[str, Any]:
        ticker = await self._ticker(symbol)

        def load() -> dict[str, Any]:
            history: list[dict[str, Any]] = []
            next_date = "N/A"

            earnings_dates = getattr(ticker, "earnings_dates", None)
            if earnings_dates is not None and not getattr(earnings_dates, "empty", True):
                table = earnings_dates.reset_index()
                for row in table.to_dict(orient="records")[:8]:
                    raw_date = row.get("Earnings Date") or row.get("Date") or row.get("index")
                    dt_value = pd.to_datetime(raw_date, errors="coerce")
                    if pd.notna(dt_value) and dt_value.tzinfo is None:
                        dt_value = dt_value.tz_localize("UTC")
                    if pd.notna(dt_value) and dt_value.date() >= date.today() and next_date == "N/A":
                        next_date = dt_value.strftime("%Y-%m-%d")

                    estimate = _to_float(row.get("EPS Estimate"))
                    actual = _to_float(row.get("Reported EPS"))
                    surprise = _to_float(row.get("Surprise(%)"))
                    history.append(
                        {
                            "quarter": dt_value.strftime("%b %Y") if pd.notna(dt_value) else "N/A",
                            "date": dt_value.strftime("%Y-%m-%d") if pd.notna(dt_value) else "N/A",
                            "estimate": estimate,
                            "actual": actual,
                            "surprise": surprise,
                        }
                    )

            if next_date == "N/A":
                calendar = getattr(ticker, "calendar", None)
                if isinstance(calendar, pd.DataFrame) and not calendar.empty:
                    idx = list(calendar.index)
                    if idx:
                        first = pd.to_datetime(idx[0], errors="coerce")
                        if pd.notna(first):
                            next_date = first.strftime("%Y-%m-%d")

            return {"history": history, "next_date": next_date}

        return await asyncio.to_thread(load)


def _df_to_records(df: pd.DataFrame | None) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    normalized = df.fillna("N/A").reset_index()
    return normalized.to_dict(orient="records")


def _holders_df_to_records(df: pd.DataFrame | None) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []

    rows: list[dict[str, Any]] = []
    for row in df.reset_index().to_dict(orient="records")[:20]:
        rows.append(
            {
                "name": row.get("Holder") or row.get("holder") or row.get("Name"),
                "shares": _to_float(row.get("Shares") or row.get("shares")),
                "pct_out": _to_float(row.get("% Out") or row.get("pctHeld") or row.get("Pct Out")),
                "value": _to_float(row.get("Value") or row.get("value")),
                "date": _format_date(row.get("Date Reported") or row.get("Date") or row.get("date")),
            }
        )
    return rows


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        if math.isnan(num) or math.isinf(num):
            return None
        return num
    text = str(value).replace("%", "").replace(",", "").replace("$", "").strip()
    if not text:
        return None
    try:
        num = float(text)
        if math.isnan(num) or math.isinf(num):
            return None
        return num
    except ValueError:
        return None


def _format_date(value: Any) -> str:
    if value is None:
        return "N/A"
    dt_value = pd.to_datetime(value, errors="coerce")
    if pd.notna(dt_value):
        return dt_value.strftime("%Y-%m-%d")
    text = str(value).strip()
    return text or "N/A"


def _source_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("displayName") or value.get("title") or value.get("name") or "Unknown")
    if value is None:
        return "Unknown"
    return str(value)
