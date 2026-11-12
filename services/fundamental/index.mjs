export function analyze(d){return d.asset_type==='equity'?{method:'demo margin only',net_margin:d.net_income/d.revenue,limitations:['No valuation or real filings']}:{method:'demo commodity inventory',inventories:d.inventories,limitations:['No real supply/demand or futures curve']};}

