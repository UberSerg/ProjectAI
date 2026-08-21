# Sources

## MOEX ISS

Base: `MOEX_BASE_URL` (default `https://iss.moex.com`)

- Shares: `/iss/history/engines/stock/markets/shares/boards/TQBR/securities/{SECID}.json`
- Indexes: `/iss/history/engines/stock/markets/index/boards/SNDX/securities/{SECID}.json`
- Pagination: `start=0,100,...`
- Close prefers `LEGALCLOSEPRICE`, fallback `CLOSE`

## Bank of Russia

Base: `CBR_BASE_URL` (default `https://www.cbr.ru`)

- Official FX: `/scripts/XML_dynamic.asp` (`R01235` USD, `R01239` EUR, `R01375` CNY)
- KEY_RATE: SOAP `DailyInfoWebServ/DailyInfo.asmx` method `KeyRateXML`
- RUONIA: SOAP method `RuoniaXML` (best-effort)

Official CBR FX series are stored separately from any exchange FX quotes.
