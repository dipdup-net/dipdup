CREATE MATERIALIZED VIEW
    candlestick_7d
AS

SELECT
    time_bucket('7 days'::INTERVAL, timestamp) AS bucket,
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

CREATE INDEX candlestick_7d_bucket ON candlestick_7d(bucket);
CREATE INDEX candlestick_7d_token_id ON candlestick_7d(token_id);
