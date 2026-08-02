# United flight fare cache

This public repository runs [`fast-flights`](https://github.com/AWeirdDev/flights) on a GitHub-hosted runner and publishes a cached JSON feed for the United Operations Flight Board.

## What it does

- Searches one-way, nonstop, non-basic United economy results from the seven major UA hubs.
- Keeps a 60-day data horizon.
- Runs a bounded batch every three hours instead of attempting the full route/date matrix at once.
- Stores only public fare-search results in `data/flights.json`.
- Preserves partial results when an individual scraper request fails.

This is a scraper, not an official Google or United API. Results can be incomplete, stale, blocked, or broken by upstream page changes. Fares are not guaranteed until confirmed with the airline.

## Run a priority scan

Open **Actions → Refresh United fare cache → Run workflow**. You may enter a departure date, one hub, and a maximum number of route searches. Leave the fields blank to continue the scheduled rotation.

The default 36 requests is intentionally conservative. Increasing it may make a run more likely to be throttled or blocked.

## Feed

The board reads:

`https://raw.githubusercontent.com/zhaojiacheng34-ai/united-flight-cache/main/data/flights.json`

No API key or Python server is required.
