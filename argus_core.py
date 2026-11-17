import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import json
import logging
import os
import re
import threading
import time
from typing import Dict, List, Optional, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ArgusCore")

# =====================================================================
#                     STAŁE SIECIOWE Z HERMESA
# =====================================================================

GATEWAY_ENDPOINT = "https://neobus.pl/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:154.0) Gecko/20100101 Firefox/154.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "pl,en-US;q=0.9,en;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://neobus.pl",
    "Referer": "https://neobus.pl/",
}

STOPS = {
    "sanok": {"id": "17", "name": "SANOK D.A. Lipińskiego"},
    "wroclaw": {"id": "77", "name": "WROCŁAW PKS Polbus"},
    "niebylec": {"id": "19", "name": "NIEBYLEC"},
    "gliwice": {
        "id": "123",
        "name": "GLIWICE Centrum Przesiadkowe ul. Składowa 8a",
    },
    "katowice": {"id": "73", "name": "KATOWICE D.A. ul. Sądowa 5"},
    "rzeszow": {"id": "76", "name": "RZESZÓW D.A. PKS"},
    "krakow": {"id": "71", "name": "KRAKÓW MDA"},
}


@dataclass
class Departure:
    route_id: str
    date: str  # DD.MM.YYYY
    departure_time: str  # HH:MM
    arrival_time: str  # HH:MM
    origin: str
    destination: str
    price: float
    free_seats: int
    is_sold_out: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class ArgusCore:
    def __init__(self, max_capacity: int = 70):
        self.max_capacity = max_capacity
        self._thread_local = threading.local()

    def get_session(self) -> requests.Session:
        if not hasattr(self._thread_local, "session"):
            s = requests.Session()
            retries = Retry(
                total=3, backoff_factor=0.4, status_forcelist=[500, 502, 503, 504]
            )
            adapter = HTTPAdapter(
                max_retries=retries, pool_connections=5, pool_maxsize=10
            )
            s.mount("https://", adapter)
            s.mount("http://", adapter)
            try:
                s.get(GATEWAY_ENDPOINT, headers=HEADERS, timeout=8)
            except Exception:
                pass
            self._thread_local.session = s
        return self._thread_local.session

    @staticmethod
    def normalize_time(t: str) -> str:
        return re.sub(r"[-]", ":", t.strip())

    def query_api(
        self,
        from_id: str,
        from_name: str,
        to_id: str,
        to_name: str,
        date_str: str,
        passengers: int = 1,
    ) -> Optional[Dict[str, dict]]:
        """
        Zwraca słownik znalezionych kursów w formacie:
        { "HH:MM": {"hours": "HH:MM -> HH:MM", "price": float} }
        """
        session = self.get_session()
        payload = {
            "ajax": "true",
            "dataType": "json",
            "module": "neotickets",
            "step": "1",
            "ticket_type": "normal",
            "initial_stop": str(from_id),
            "final_stop": str(to_id),
            "passengers": str(passengers),
            "date_there": date_str,
            "date_return": "",
            "initial_stop_name": from_name,
            "final_stop_name": to_name,
        }

        for attempt in range(2):
            try:
                r = session.post(
                    GATEWAY_ENDPOINT, data=payload, headers=HEADERS, timeout=7
                )
                if r.status_code != 200:
                    time.sleep(0.15)
                    continue

                raw = r.json() if hasattr(r, "json") else json.loads(r.text)
                content = (
                    raw.get("neotickets", raw) if isinstance(raw, dict) else raw
                )
                data = (
                    json.loads(content)
                    if isinstance(content, str)
                    else content
                )

                courses = {}
                if (
                    isinstance(data, dict)
                    and "ga4_data" in data
                    and len(data["ga4_data"]) > 0
                ):
                    for it in data["ga4_data"][0].get("items", []):
                        name = it.get("item_name", "")
                        price = float(
                            it.get("price") or it.get("discount", 0.0) or 0.0
                        )
                        m = re.search(
                            r"(\d{2}[-:]\d{2})\s*-\s*(\d{2}[-:]\d{2})", name
                        )
                        if m and price > 0:
                            dep = self.normalize_time(m.group(1))
                            arr = self.normalize_time(m.group(2))
                            courses[dep] = {
                                "hours": f"{dep} -> {arr}",
                                "dep": dep,
                                "arr": arr,
                                "price": price,
                            }
                return courses
            except Exception:
                time.sleep(0.15)
        return None

    def query_day_seats_map(
        self,
        from_id: str,
        from_name: str,
        to_id: str,
        to_name: str,
        date_str: str,
        passengers: int,
    ) -> Optional[set]:
        data = self.query_api(
            from_id, from_name, to_id, to_name, date_str, passengers=passengers
        )
        if data is None:
            return None
        return set(data.keys())

    def resolve_course_adaptive(
        self,
        from_id: str,
        from_name: str,
        to_id: str,
        to_name: str,
        date_str: str,
        dep: str,
        prev_val: Optional[int] = None,
    ) -> int:
        """
        Szybki algorytm adaptacyjny badający liczbę wolnych miejsc (1..MAX_CAPACITY).
        """
        if (
            prev_val
            and isinstance(prev_val, int)
            and 1 < prev_val <= self.max_capacity
        ):
            map_prev = self.query_day_seats_map(
                from_id, from_name, to_id, to_name, date_str, prev_val
            )
            if map_prev is not None and dep in map_prev:
                if prev_val < self.max_capacity:
                    map_plus = self.query_day_seats_map(
                        from_id,
                        from_name,
                        to_id,
                        to_name,
                        date_str,
                        min(self.max_capacity, prev_val + 2),
                    )
                    if map_plus is not None and dep in map_plus:
                        return min(self.max_capacity, prev_val + 2)
                return prev_val
            else:
                low, high = 1, prev_val - 1
        else:
            map_50 = self.query_day_seats_map(
                from_id, from_name, to_id, to_name, date_str, 50
            )
            if map_50 is not None and dep in map_50:
                map_max = self.query_day_seats_map(
                    from_id, from_name, to_id, to_name, date_str, self.max_capacity
                )
                if map_max is not None and dep in map_max:
                    return self.max_capacity
                return 50
            low, high = 1, 49

        exact = 1
        while low <= high:
            mid = (low + high) // 2
            day_map = self.query_day_seats_map(
                from_id, from_name, to_id, to_name, date_str, mid
            )
            if day_map is None:
                return (
                    prev_val
                    if (prev_val and isinstance(prev_val, int))
                    else 1
                )
            if dep in day_map:
                exact = mid
                low = mid + 1
            else:
                high = mid - 1
            time.sleep(0.01)

        return exact

    def fetch_route_day(
        self,
        from_key: str,
        to_key: str,
        date_str: str,
        check_seats: bool = False,
        prev_seats: Optional[Dict[str, int]] = None,
    ) -> List[Departure]:
        """
        Pobiera kursy dla zadanego kierunku i daty (DD.MM.YYYY).
        """
        f_stop = STOPS.get(from_key.lower())
        t_stop = STOPS.get(to_key.lower())
        if not f_stop or not t_stop:
            raise ValueError(f"Nieznany przystanek: {from_key} lub {to_key}")

        raw_courses = self.query_api(
            f_stop["id"], f_stop["name"], t_stop["id"], t_stop["name"], date_str, 1
        )
        if not raw_courses:
            return []

        results: List[Departure] = []
        for dep, info in raw_courses.items():
            seats = 9
            if check_seats:
                prev_s = prev_seats.get(dep) if prev_seats else None
                seats = self.resolve_course_adaptive(
                    f_stop["id"],
                    f_stop["name"],
                    t_stop["id"],
                    t_stop["name"],
                    date_str,
                    dep,
                    prev_s,
                )

            route_id = f"{from_key}_{to_key}_{date_str}_{dep.replace(':', '')}"
            results.append(
                Departure(
                    route_id=route_id,
                    date=date_str,
                    departure_time=info["dep"],
                    arrival_time=info["arr"],
                    origin=f_stop["name"],
                    destination=t_stop["name"],
                    price=info["price"],
                    free_seats=seats,
                    is_sold_out=(seats == 0),
                )
            )

        return sorted(results, key=lambda x: x.departure_time)


if __name__ == "__main__":
    core = ArgusCore()
    today_str = (date.today() + timedelta(days=5)).strftime("%d.%m.%Y")
    print(f"Test pobierania Wrocław -> Sanok na {today_str}...")
    kursy = core.fetch_route_day("wroclaw", "sanok", today_str, check_seats=False)
    print(f"Znaleziono {len(kursy)} kursów:")
    for k in kursy:
        print(f"  {k.departure_time} -> {k.arrival_time} | {k.price:.2f} zł")
