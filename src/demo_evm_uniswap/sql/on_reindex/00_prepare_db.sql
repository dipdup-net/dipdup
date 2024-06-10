CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

ALTER TABLE swap DROP CONSTRAINT swap_pkey;
ALTER TABLE swap ADD PRIMARY KEY (id, timestamp);
SELECT create_hypertable('swap', 'timestamp');

CREATE TABLE grafana_query
(
    id        integer
        constraint grafana_query_id_pk
            primary key,
    type      text not null,
    intervals jsonb,
    query     text
);

create index grafana_query_intervals_index on grafana_query (intervals);
create index grafana_query_type_index on grafana_query (type);

insert into grafana_query (id, type, intervals, query)
values  (1, 'data', '["1m", "5m", "15m", "1h", "6h"]', 'WITH cs AS ( SELECT time_bucket(''$cs_interval'', timestamp) AS bucket, candlestick_agg( timestamp, abs(amount_usd / amount0), amount_usd ) as candlestick FROM swap WHERE token0_id = ''$token_id'' AND amount_usd!=0 AND amount0!=0 AND $__timeFilter(timestamp) GROUP BY bucket ) select bucket as time, open(candlestick) AS open, high(candlestick) AS high, low(candlestick) AS low, close(candlestick) AS close, vwap(candlestick) AS vwap, volume(candlestick) AS volume FROM cs WHERE ''$cs_interval'' not in (''1d'', ''7d'', ''30d'');'),
        (2, 'data', '["1d", "7d", "30d"]', 'select bucket as time, open(candlestick) AS open, high(candlestick) AS high, low(candlestick) AS low, close(candlestick) AS close, vwap(candlestick) AS vwap, volume(candlestick) AS volume FROM candlestick_$cs_interval WHERE token_id = ''$token_id'' AND $__timeFilter(bucket);'),
        (3, 'token', '["1m", "5m", "15m", "1h", "6h"]', 'with s as ( select distinct on (token0_id) token0_id AS token_id from swap as q where $__timeFilter(q.timestamp) ) select s.token_id as __value, concat(t.symbol, '' ('',t.name, '')'') AS __text, t.volume_usd from s join token as t on t.id = s.token_id where t.tx_count > 128 order by t.volume_usd desc;'),
        (4, 'token', '["1d", "7d", "30d"]', 'with s as ( select distinct on (token_id) token_id from candlestick_$cs_interval as q where $__timeFilter(q.bucket) ) select s.token_id as __value, concat(t.symbol, '' ('',t.name, '')'') AS __text, t.volume_usd from s join token as t on t.id = s.token_id where t.tx_count > 128 order by t.volume_usd desc;');
