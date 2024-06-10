CREATE MATERIALIZED VIEW
    candlestick_30d
AS

SELECT
    time_bucket('30 days'::INTERVAL, timestamp) AS bucket,
    token0_id as token_id,
    candlestick_agg(
        timestamp,
        abs(amount_usd/amount0),
        amount_usd
    ) as candlestick
FROM swap
    WHERE
        amount_usd!=0
    AND
        amount0!=0

GROUP BY
    bucket,
    token0_id
ORDER BY
    bucket,
    token0_id
WITH NO DATA;

CREATE INDEX candlestick_30d_bucket ON candlestick_30d(bucket);
CREATE INDEX candlestick_30d_token_id ON candlestick_30d(token_id);
