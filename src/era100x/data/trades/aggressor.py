from era100x.data.schema.models import NormalizedTrade


def with_aggressor_side(trade: NormalizedTrade) -> NormalizedTrade:
    return trade.model_copy(update={"aggressor_side": "SELL" if trade.is_buyer_maker else "BUY"})
