#!/usr/bin/env python3
"""Refresh a bounded slice of the United fare cache with fast-flights."""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from fast_flights import FlightQuery, Passengers, create_query, get_flights


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
DATA_PATH = ROOT / "data" / "flights.json"
STATE_PATH = ROOT / "data" / "state.json"


def read_json(path: Path, fallback: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def iso_day(value: date) -> str:
    return value.isoformat()


def route_key(departure_date: str, origin: str, destination: str) -> str:
    return f"{departure_date}|{origin}|{destination}"


def build_matrix(config: dict, target_date: str, target_hub: str) -> list[tuple[str, str, str]]:
    tomorrow = date.today() + timedelta(days=1)
    horizon = int(config.get("horizon_days", 60))
    dates = [iso_day(tomorrow + timedelta(days=offset)) for offset in range(horizon)]

    if target_date:
        parsed = date.fromisoformat(target_date)
        if parsed < tomorrow or parsed >= tomorrow + timedelta(days=horizon):
            raise ValueError(f"TARGET_DATE must be between {tomorrow} and {tomorrow + timedelta(days=horizon - 1)}")
        dates = [target_date]

    hubs = [str(item).upper() for item in config["hubs"]]
    if target_hub:
        target_hub = target_hub.upper()
        if target_hub not in hubs:
            raise ValueError(f"TARGET_HUB must be one of {', '.join(hubs)}")
        hubs = [target_hub]

    destinations = [str(item).upper() for item in config["destinations"]]
    return [
        (departure_date, hub, destination)
        for departure_date in dates
        for hub in hubs
        for destination in destinations
        if destination != hub
    ]


def clock(value: tuple[int, int]) -> str:
    return f"{int(value[0]):02d}:{int(value[1]):02d}"


def search_route(departure_date: str, origin: str, destination: str) -> tuple[list[dict], str]:
    query = create_query(
        flights=[
            FlightQuery(
                date=departure_date,
                from_airport=origin,
                to_airport=destination,
                max_stops=0,
                airlines=["UA"],
            )
        ],
        seat="economy",
        trip="one-way",
        passengers=Passengers(adults=1),
        language="en",
        currency="USD",
        exclude_basic_economy=True,
    )
    results = get_flights(query)
    search_url = "https://www.google.com/travel/flights/search?tfs=" + quote(query.to_str()) + "&curr=USD&hl=en"
    flights: list[dict] = []

    for option_index, option in enumerate(results):
        if len(option.flights) != 1 or not option.price:
            continue
        leg = option.flights[0]
        if leg.from_airport.code.upper() != origin or leg.to_airport.code.upper() != destination:
            continue
        airlines = [str(item) for item in option.airlines]
        if airlines and not any("united" in item.lower() or item.upper() == "UA" for item in airlines):
            continue
        departure = clock(leg.departure.time)
        arrival = clock(leg.arrival.time)
        flight_id = f"{origin}-{destination}-{departure_date}-{departure}-{arrival}-{leg.duration}-{option.price}-{option_index}"
        flights.append(
            {
                "id": flight_id,
                "origin": origin,
                "destination": destination,
                "destinationCity": leg.to_airport.name or destination,
                "date": departure_date,
                "departure": departure,
                "arrival": arrival,
                "duration": int(leg.duration),
                "price": int(option.price),
                "airline": ", ".join(airlines) if airlines else "United",
                "priceSignal": "standard economy",
                "buyLink": search_url,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )
    return flights, search_url


def main() -> None:
    config = read_json(CONFIG_PATH, {})
    data = read_json(DATA_PATH, {"flights": [], "routes": {}})
    state = read_json(STATE_PATH, {"scheduledCursor": 0, "manualCursors": {}})

    target_date = os.getenv("TARGET_DATE", "").strip()
    target_hub = os.getenv("TARGET_HUB", "").strip().upper()
    default_limit = int(config.get("scheduled_routes_per_run", 36))
    limit = max(1, min(int(os.getenv("MAX_ROUTES", str(default_limit))), 175))
    matrix = build_matrix(config, target_date, target_hub)
    if not matrix:
        raise RuntimeError("No route/date combinations were generated")

    cursor_key = f"{target_date or 'scheduled'}|{target_hub or 'all'}"
    if target_date or target_hub:
        cursor = int(state.setdefault("manualCursors", {}).get(cursor_key, 0)) % len(matrix)
    else:
        cursor = int(state.get("scheduledCursor", 0)) % len(matrix)

    selected = [matrix[(cursor + offset) % len(matrix)] for offset in range(min(limit, len(matrix)))]
    flights_by_id = {item["id"]: item for item in data.get("flights", []) if item.get("id")}
    routes = data.setdefault("routes", {})
    successful = 0
    failed = 0

    for index, (departure_date, origin, destination) in enumerate(selected, start=1):
        key = route_key(departure_date, origin, destination)
        print(f"[{index}/{len(selected)}] {origin}-{destination} on {departure_date}", flush=True)
        try:
            found, search_url = search_route(departure_date, origin, destination)
            flights_by_id = {
                item_id: item
                for item_id, item in flights_by_id.items()
                if not (
                    item.get("date") == departure_date
                    and item.get("origin") == origin
                    and item.get("destination") == destination
                )
            }
            for item in found:
                flights_by_id[item["id"]] = item
            routes[key] = {
                "date": departure_date,
                "origin": origin,
                "destination": destination,
                "status": "ok",
                "flightCount": len(found),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "searchUrl": search_url,
            }
            successful += 1
        except Exception as exc:  # keep useful results when one scraper request fails
            routes[key] = {
                "date": departure_date,
                "origin": origin,
                "destination": destination,
                "status": "error",
                "flightCount": 0,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            }
            print(f"  failed: {type(exc).__name__}: {exc}", flush=True)
            failed += 1
        time.sleep(0.25)

    next_cursor = (cursor + len(selected)) % len(matrix)
    if target_date or target_hub:
        state.setdefault("manualCursors", {})[cursor_key] = next_cursor
    else:
        state["scheduledCursor"] = next_cursor

    tomorrow = date.today() + timedelta(days=1)
    horizon_end = tomorrow + timedelta(days=int(config.get("horizon_days", 60)) - 1)
    flights = [
        item
        for item in flights_by_id.values()
        if iso_day(tomorrow) <= str(item.get("date", "")) <= iso_day(horizon_end)
    ]
    routes = {
        key: value
        for key, value in routes.items()
        if iso_day(tomorrow) <= str(value.get("date", "")) <= iso_day(horizon_end)
    }
    flights.sort(key=lambda item: (item.get("price", 10**9), item.get("date", ""), item.get("origin", "")))

    routes_per_date = sum(1 for hub in config["hubs"] for destination in config["destinations"] if destination != hub)
    total_route_dates = routes_per_date * int(config.get("horizon_days", 60))
    covered = sum(1 for value in routes.values() if value.get("status") == "ok")
    data = {
        "schemaVersion": 1,
        "source": "fast-flights",
        "provider": "Google Flights results via fast-flights",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "horizonStart": iso_day(tomorrow),
        "horizonEnd": iso_day(horizon_end),
        "totalRouteDates": total_route_dates,
        "coveredRouteDates": covered,
        "coveragePercent": round(covered / total_route_dates * 100, 2) if total_route_dates else 0,
        "successfulChecks": successful,
        "failedChecks": failed,
        "flights": flights,
        "routes": routes,
    }
    write_json(DATA_PATH, data)
    write_json(STATE_PATH, state)
    print(f"Saved {len(flights)} flights; {covered}/{total_route_dates} route-dates covered", flush=True)


if __name__ == "__main__":
    main()
