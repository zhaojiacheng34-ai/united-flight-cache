from datetime import datetime, timedelta, timezone
import unittest

from scripts.cache_plan import route_key, select_scheduled


NOW = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)


def route(day, origin, destination, status, age_hours):
    return {
        "date": day,
        "origin": origin,
        "destination": destination,
        "status": status,
        "updatedAt": (NOW - timedelta(hours=age_hours)).isoformat(),
    }


class SelectionTests(unittest.TestCase):
    def test_missing_routes_are_selected_before_usable_routes(self):
        matrix = [("2026-08-03", "EWR", code) for code in ("BOS", "ORD", "SFO")]
        complete = route("2026-08-03", "EWR", "BOS", "ok", 1)
        days = {"2026-08-03": {"routes": {route_key("2026-08-03", "EWR", "BOS"): complete}}}

        selected = select_scheduled(matrix, days, 2, 0, 12, 72, NOW)

        self.assertEqual(selected, matrix[1:])

    def test_retry_capacity_is_bounded_during_backfill(self):
        matrix = [("2026-08-03", "EWR", code) for code in ("BOS", "ORD", "SFO", "LAX")]
        routes = {
            route_key("2026-08-03", "EWR", code): route(
                "2026-08-03", "EWR", code, "parser_error", 24
            )
            for code in ("BOS", "ORD")
        }
        days = {"2026-08-03": {"routes": routes}}

        selected = select_scheduled(matrix, days, 3, 1, 12, 72, NOW)

        self.assertEqual(selected, [matrix[0], matrix[2], matrix[3]])

    def test_recent_errors_wait_for_retry_window(self):
        matrix = [("2026-08-03", "EWR", "BOS"), ("2026-08-03", "EWR", "ORD")]
        recent_error = route("2026-08-03", "EWR", "BOS", "parser_error", 2)
        days = {"2026-08-03": {"routes": {route_key(*matrix[0]): recent_error}}}

        selected = select_scheduled(matrix, days, 2, 1, 12, 72, NOW)

        self.assertEqual(selected, [matrix[1]])

    def test_oldest_routes_refresh_after_backfill(self):
        matrix = [("2026-08-03", "EWR", "BOS"), ("2026-08-03", "EWR", "ORD")]
        routes = {
            route_key(*matrix[0]): route(*matrix[0], "ok", 80),
            route_key(*matrix[1]): route(*matrix[1], "no_results", 100),
        }
        days = {"2026-08-03": {"routes": routes}}

        selected = select_scheduled(matrix, days, 1, 1, 12, 72, NOW)

        self.assertEqual(selected, [matrix[1]])


if __name__ == "__main__":
    unittest.main()
