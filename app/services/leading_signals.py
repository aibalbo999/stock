from __future__ import annotations

from dataclasses import dataclass, field

from app.models.schemas import MarketSnapshot, MonthlyRevenue, ValuationMetric


@dataclass(frozen=True)
class LeadingSignal:
    ticker: str
    score: int
    upside_bonus: int
    downside_penalty: int
    price_20d_pct: float | None = None
    price_60d_pct: float | None = None
    volume_ratio_20d: float | None = None
    revenue_yoy_pct: float | None = None
    revenue_acceleration_pct: float | None = None
    valuation_label: str = "未評估"
    bullish_factors: list[str] = field(default_factory=list)
    bearish_factors: list[str] = field(default_factory=list)
    neutral_factors: list[str] = field(default_factory=list)

    @property
    def direction(self) -> str:
        if self.score >= 5:
            return "偏多"
        if self.score <= -5:
            return "偏空"
        return "中性"

    @property
    def summary(self) -> str:
        factors = self.bullish_factors if self.score >= 0 else self.bearish_factors
        if not factors:
            factors = self.neutral_factors
        return "；".join(factors[:3]) if factors else "目前無足夠領先訊號。"


class LeadingSignalAnalyzer:
    def build(
        self,
        tickers: list[str],
        price_histories: dict[str, list[MarketSnapshot]],
        revenue_histories: dict[str, list[MonthlyRevenue]],
        valuations: dict[str, ValuationMetric],
        peer_valuation_summary: dict[str, float | None],
    ) -> dict[str, LeadingSignal]:
        return {
            ticker: self.analyze(
                ticker,
                price_histories.get(ticker, []),
                revenue_histories.get(ticker, []),
                valuations.get(ticker),
                peer_valuation_summary,
            )
            for ticker in tickers
        }

    def analyze(
        self,
        ticker: str,
        prices: list[MarketSnapshot],
        revenues: list[MonthlyRevenue],
        valuation: ValuationMetric | None = None,
        peer_valuation_summary: dict[str, float | None] | None = None,
    ) -> LeadingSignal:
        bullish: list[str] = []
        bearish: list[str] = []
        neutral: list[str] = []
        upside_bonus = 0
        downside_penalty = 0

        price_20d_pct = self._price_change(prices, 20)
        price_60d_pct = self._price_change(prices, 60)
        volume_ratio_20d = self._volume_ratio(prices, 20)
        if price_20d_pct is not None:
            if price_20d_pct >= 8:
                upside_bonus += 3
                bullish.append(f"20 日股價動能 +{price_20d_pct:.1f}%")
            elif price_20d_pct <= -8:
                downside_penalty += 3
                bearish.append(f"20 日股價轉弱 {price_20d_pct:.1f}%")
            else:
                neutral.append(f"20 日股價 {price_20d_pct:.1f}%")
        else:
            neutral.append("股價歷史不足 20 日")

        if price_60d_pct is not None:
            if price_60d_pct >= 15:
                upside_bonus += 3
                bullish.append(f"60 日趨勢 +{price_60d_pct:.1f}%")
            elif price_60d_pct <= -12:
                downside_penalty += 4
                bearish.append(f"60 日趨勢轉弱 {price_60d_pct:.1f}%")
        elif prices:
            neutral.append("股價歷史不足 60 日")

        latest_close = prices[-1].close if prices else None
        previous_close = prices[-2].close if len(prices) >= 2 else None
        latest_down = latest_close is not None and previous_close is not None and latest_close < previous_close
        if volume_ratio_20d is not None:
            if volume_ratio_20d >= 1.5 and not latest_down:
                upside_bonus += 2
                bullish.append(f"量能放大至 20 日均量 {volume_ratio_20d:.1f} 倍")
            elif volume_ratio_20d >= 1.5 and latest_down:
                downside_penalty += 2
                bearish.append(f"下跌伴隨量能放大 {volume_ratio_20d:.1f} 倍")

        revenue_yoy_pct, revenue_acceleration_pct = self._revenue_signal(revenues)
        if revenue_yoy_pct is not None:
            if revenue_yoy_pct >= 20:
                upside_bonus += 4
                bullish.append(f"月營收年增 {revenue_yoy_pct:.1f}%")
            elif revenue_yoy_pct >= 10:
                upside_bonus += 2
                bullish.append(f"月營收年增 {revenue_yoy_pct:.1f}%")
            elif revenue_yoy_pct < 0:
                downside_penalty += 4
                bearish.append(f"月營收年減 {abs(revenue_yoy_pct):.1f}%")
            else:
                neutral.append(f"月營收年增 {revenue_yoy_pct:.1f}%")
        else:
            neutral.append("月營收 YoY 不足")

        if revenue_acceleration_pct is not None:
            if revenue_acceleration_pct >= 5:
                upside_bonus += 3
                bullish.append(f"營收成長加速 {revenue_acceleration_pct:.1f} 個百分點")
            elif revenue_acceleration_pct <= -5:
                downside_penalty += 3
                bearish.append(f"營收成長放緩 {abs(revenue_acceleration_pct):.1f} 個百分點")

        valuation_label = self._valuation_label(valuation, peer_valuation_summary or {})
        if valuation_label == "低於同業":
            upside_bonus += 2
            bullish.append("估值低於同業")
        elif valuation_label == "高於同業":
            downside_penalty += 2
            bearish.append("估值高於同業")

        return LeadingSignal(
            ticker=ticker,
            score=upside_bonus - downside_penalty,
            upside_bonus=upside_bonus,
            downside_penalty=downside_penalty,
            price_20d_pct=price_20d_pct,
            price_60d_pct=price_60d_pct,
            volume_ratio_20d=volume_ratio_20d,
            revenue_yoy_pct=revenue_yoy_pct,
            revenue_acceleration_pct=revenue_acceleration_pct,
            valuation_label=valuation_label,
            bullish_factors=bullish,
            bearish_factors=bearish,
            neutral_factors=neutral,
        )

    @staticmethod
    def _price_change(prices: list[MarketSnapshot], days: int) -> float | None:
        if len(prices) <= days:
            return None
        latest = prices[-1].close
        base = prices[-days - 1].close
        if latest is None or base in (None, 0):
            return None
        return round((latest - base) / base * 100, 2)

    @staticmethod
    def _volume_ratio(prices: list[MarketSnapshot], days: int) -> float | None:
        if len(prices) < days + 1 or prices[-1].trading_volume is None:
            return None
        volumes = [price.trading_volume for price in prices[-days - 1:-1] if price.trading_volume]
        if not volumes:
            return None
        return round(prices[-1].trading_volume / (sum(volumes) / len(volumes)), 2)

    @staticmethod
    def _revenue_signal(revenues: list[MonthlyRevenue]) -> tuple[float | None, float | None]:
        yoy_values = [revenue.yoy_pct for revenue in revenues if revenue.yoy_pct is not None]
        if not yoy_values:
            return None, None
        latest = yoy_values[-1]
        previous = yoy_values[-2] if len(yoy_values) >= 2 else None
        acceleration = round(latest - previous, 2) if previous is not None else None
        return latest, acceleration

    @staticmethod
    def _valuation_label(
        valuation: ValuationMetric | None,
        peer_summary: dict[str, float | None],
    ) -> str:
        if not valuation:
            return "未評估"
        pe_avg = peer_summary.get("pe_avg")
        pb_avg = peer_summary.get("pb_avg")
        low_count = 0
        high_count = 0
        if valuation.pe_ratio is not None and pe_avg:
            low_count += int(valuation.pe_ratio < pe_avg * 0.9)
            high_count += int(valuation.pe_ratio > pe_avg * 1.1)
        if valuation.pb_ratio is not None and pb_avg:
            low_count += int(valuation.pb_ratio < pb_avg * 0.9)
            high_count += int(valuation.pb_ratio > pb_avg * 1.1)
        if low_count > high_count:
            return "低於同業"
        if high_count > low_count:
            return "高於同業"
        return "接近同業"
