"""Selection helpers for bounded expanded-cache refreshes."""

from __future__ import annotations

from datetime import datetime, timezone


Route = tuple[str, str, str]


def route_key(departure_date: str, origin: str, destination: str) -> str:
    return f"{departure_date}|{origin}|{destination}"


def _updated_at(route: dict) -> datetime:
    value = str(route.get("updatedAt", ""))
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def select_scheduled(
    matrix: list[Route],
    days: dict[str, dict],
    limit: int,
    retry_limit: int,
    retry_after_hours: float,
    refresh_after_hours: float,
    now: datetime,
) -> list[Route]:
    """Prioritize missing coverage, while reserving bounded retry capacity."""
    pending: list[Route] = []
    retries: list[tuple[datetime, Route]] = []
    stale: list[tuple[datetime, Route]] = []

    for candidate in matrix:
        departure_date, origin, destination = candidate
        route = days.get(departure_date, {}).get("routes", {}).get(
            route_key(departure_date, origin, destination)
        )
        if route is None:
            pending.append(candidate)
            continue

        updated_at = _updated_at(route)
        age_hours = (now - updated_at).total_seconds() / 3600
        if route.get("status") in {"parser_error", "error"}:
            if age_hours >= retry_after_hours:
                retries.append((updated_at, candidate))
        elif age_hours >= refresh_after_hours:
            stale.append((updated_at, candidate))

    retries.sort(key=lambda item: item[0])
    stale.sort(key=lambda item: item[0])

    if pending:
        retry_slots = min(max(0, retry_limit), len(retries), limit)
        selected = [candidate for _, candidate in retries[:retry_slots]]
        selected.extend(pending[: max(0, limit - len(selected))])
        return selected

    maintenance = retries + stale
    maintenance.sort(key=lambda item: item[0])
    return [candidate for _, candidate in maintenance[:limit]]
