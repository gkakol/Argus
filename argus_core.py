from dataclasses import asdict, dataclass
import json
import logging
import os
import re
import threading
import time
from typing import Dict, List, Optional, Set, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ArgusCore")

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
    direction: str  # "THERE" lub "RETURN"
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
                total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504]
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

    def _execute_post(self, payload: dict) -> Optional[dict]:
        session = self.get_session()
        for attempt in range(2):
            try:
                r = session.post(
                    GATEWAY_ENDPOINT, data=payload, headers=HEADERS, timeout=7
                )
                if r.status_code != 200:
                    time.sleep(0.1)
                    continue

                raw = r.json() if hasattr(r, "json") else json.loads(r.text)
                content = raw.get("neotickets", raw) if isinstance(raw, dict) else raw
                data = json.loads(content) if isinstance(content, str) else content
                if isinstance(data, dict):
                    return data
            except Exception:
                time.sleep(0.1)
        return None

    def _parse_ga4_items(self, items: list) -> Dict[str, dict]:
        courses = {}
        for it in items:
            name = it.get("item_name", "")
            price = float(it.get("price") or it.get("discount", 0.0) or 0.0)
            m = re.search(r"(\d{2}[-:]\d{2})\s*-\s*(\d{2}[-:]\d{2})", name)
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

    def query_roundtrip_raw(
        self,
        from_id: str,
        from_name: str,
        to_id: str,
        to_name: str,
        date_str: str,
        passengers: int = 1,
    ) -> Tuple[Optional[Dict[str, dict]], Optional[Dict[str, dict]]]:
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
            "date_return": date_str,
            "initial_stop_name": from_name,
            "final_stop_name": to_name,
        }

        data = self._execute_post(payload)
        if not data or "ga4_data" not in data or len(data["ga4_data"]) == 0:
            return None, None

        ga4 = data["ga4_data"]
        there = self._parse_ga4_items(ga4[0].get("items", [])) if len(ga4) > 0 else {}
        ret = self._parse_ga4_items(ga4[1].get("items", [])) if len(ga4) > 1 else {}
        return there, ret

    def fetch_roundtrip_day(
        self,
        from_key: str,
        to_key: str,
        date_str: str,
        check_seats: bool = False,
    ) -> Tuple[List[Departure], List[Departure]]:
        """
        Zoptymalizowana wersja kolektywna:
        Zamiast odpytywać każdy kurs osobno, wykonuje globalny binary search (maks. 6-7 zapytań na cały dzień!).
        """
        f_stop = STOPS.get(from_key.lower())
        t_stop = STOPS.get(to_key.lower())
        if not f_stop or not t_stop:
            raise ValueError(f"Nieznany przystanek: {from_key} lub {to_key}")

        # 1. Bazowe zapytanie (passengers=1) - wykrywa wszystkie dostępne kursy
        there_base, return_base = self.query_roundtrip_raw(
            f_stop["id"], f_stop["name"], t_stop["id"], t_stop["name"], date_str, passengers=1
        )
        if not there_base and not return_base:
            return [], []

        # Struktura kursów do monitorowania
        all_courses = []
        for dep, info in (there_base or {}).items():
            all_courses.append({
                "dep": dep, "info": info, "direction": "THERE",
                "low": 1, "high": self.max_capacity, "exact": 1
            })
        for dep, info in (return_base or {}).items():
            all_courses.append({
                "dep": dep, "info": info, "direction": "RETURN",
                "low": 1, "high": self.max_capacity, "exact": 1
            })

        # 2. Kolektywny binary search (jeśli włączony)
        if check_seats and all_courses:
            cache = {1: (set(there_base.keys()), set(return_base.keys()))}

            # Szybki check dla 50 i MAX_CAPACITY (często kursy są prawie puste)
            for probe in [self.max_capacity, 50]:
                t_map, r_map = self.query_roundtrip_raw(
                    f_stop["id"], f_stop["name"], t_stop["id"], t_stop["name"], date_str, probe
                )
                if t_map is not None:
                    cache[probe] = (set(t_map.keys()), set(r_map.keys()))
                    for c in all_courses:
                        active = cache[probe][0] if c["direction"] == "THERE" else cache[probe][1]
                        if c["dep"] in active:
                            c["low"] = probe
                            c["exact"] = max(c["exact"], probe)
                        else:
                            c["high"] = min(c["high"], probe - 1)

            # Pętla binary search dopóki jakikolwiek kurs ma nierozstrzygnięty przedział
            while True:
                pending = [c for c in all_courses if c["low"] < c["high"]]
                if not pending:
                    break

                # Wybieramy mid jednego z nieustalonych kursów
                mid = (pending[0]["low"] + pending[0]["high"]) // 2

                if mid not in cache:
                    t_map, r_map = self.query_roundtrip_raw(
                        f_stop["id"], f_stop["name"], t_stop["id"], t_stop["name"], date_str, mid
                    )
                    if t_map is None:
                        # W razie błędu sieci przerywamy i zostawiamy dotychczasowe oszacowanie
                        break
                    cache[mid] = (set(t_map.keys()), set(r_map.keys()))

                active_there, active_ret = cache[mid]

                for c in all_courses:
                    if c["low"] >= c["high"]:
                        continue
                    active = active_there if c["direction"] == "THERE" else active_ret
                    if c["dep"] in active:
                        c["exact"] = mid
                        c["low"] = mid + 1
                    else:
                        c["high"] = mid - 1

        # 3. Złożenie wynikowych obiektów Departure
        there_courses: List[Departure] = []
        return_courses: List[Departure] = []

        for c in all_courses:
            dep_obj = Departure(
                route_id=f"{from_key}_{to_key}_{date_str}_{c['dep'].replace(':', '')}" if c["direction"] == "THERE" else f"{to_key}_{from_key}_{date_str}_{c['dep'].replace(':', '')}",
                date=date_str,
                departure_time=c["info"]["dep"],
                arrival_time=c["info"]["arr"],
                origin=f_stop["name"] if c["direction"] == "THERE" else t_stop["name"],
                destination=t_stop["name"] if c["direction"] == "THERE" else f_stop["name"],
                price=c["info"]["price"],
                free_seats=c["exact"],
                direction=c["direction"],
                is_sold_out=(c["exact"] == 0),
            )
            if c["direction"] == "THERE":
                there_courses.append(dep_obj)
            else:
                return_courses.append(dep_obj)

        there_courses.sort(key=lambda x: x.departure_time)
        return_courses.sort(key=lambda x: x.departure_time)
        return there_courses, return_courses
