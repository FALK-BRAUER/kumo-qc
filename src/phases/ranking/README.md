# ranking phases

Ranking phases reorder or filter already-qualified ticker candidates before entry confirmation.
Use this directory for candidate-priority logic that consumes context from `rebalance`, `signal`, and prior watchlist state.
Learned rankers must remain opt-in and consume only deployable runtime artifacts/features; George labels, OCR, transcripts, and watchlists are not live ranking inputs.
Do not place sizing, broker order mechanics, or exit logic here.
