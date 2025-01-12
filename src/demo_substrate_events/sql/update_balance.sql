insert into holder (
    address
    ,balance
    ,turnover
    ,tx_count
    ,last_seen
)
values (
    :address
    ,:amount
    ,abs(:amount)
    ,1
    ,:level
)
on conflict (address) do
update
set
    balance = balance + :amount
    ,turnover = turnover + abs(:amount)
    ,tx_count = tx_count + 1
    ,last_seen = :level
;