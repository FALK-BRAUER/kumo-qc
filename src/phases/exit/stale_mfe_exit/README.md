# stale_mfe_exit
Intraday exit for positions that stop making fresh MFE for a configurable number of trading sessions.
Use this to test stale-runner and age-cap realization logic while consuming the shared `position_path` contract.
Do not put scanner ranking, entry selection, or broker protective-stop lifecycle code here.
