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

    def _execute_post(self, payload: dict) -> Optional[dict]:
        session = self.get_session()
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
                if isinstance(data, dict):
                    return data
            except Exception:
                time.sleep(0.15)
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
        """
        Pobiera surowe dane kursów w obu kierunkach dla zadanej liczby pasażerów.
        Zwraca: (slownik_tam, slownik_powrot) lub (None, None) w razie błędu.
        """
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

    def _query_active_times(
        self, from_id: str, from_name: str, to_id: str, to_name: str, date_str: str, passengers: int
    ) -> Tuple[Optional[Set[str]], Optional[Set[str]]]:
        there_map, ret_map = self.query_roundtrip_raw(
            from_id, from_name, to_id, to_name, date_str, passengers=passengers
        )
        if there_map is None and ret_map is None:
            return None, None
        return (
            set(there_map.keys()) if there_map is not None else set(),
            set(ret_map.keys()) if ret_map is not None else set(),
        )

    def _resolve_single_course(
        self,
        from_id: str,
        from_name: str,
        to_id: str,
        to_name: str,
        date_str: str,
        dep_time: str,
        direction: str,
        prev_val: Optional[int] = None,
    ) -> int:
        """
        Wyznacza dokładną liczbę wolnych miejsc (1..MAX_CAPACITY) dla pojedynczego kursu.
        """
        def check_dep_exists(pass_cnt: int) -> Optional[bool]:
            t_set, r_set = self._query_active_times(
                from_id, from_name, to_id, to_name, date_str, pass_cnt
            )
            target = t_set if direction == "THERE" else r_set
            if target is None:
                return None
            return dep_time in target

        # 1. Sprawdzenie z użyciem wartości historycznej
        if prev_val and isinstance(prev_val, int) and 1 < prev_val <= self.max_capacity:
            res = check_dep_exists(prev_val)
            if res is True:
                if prev_val < self.max_capacity:
                    res_plus = check_dep_exists(min(self.max_capacity, prev_val + 2))
                    if res_plus is True:
                        return min(self.max_capacity, prev_val + 2)
                return prev_val
            elif res is False:
                low, high = 1, prev_val - 1
            else:
                return prev_val
        else:
            # 2. Szybka sonda na 50 i MAX_CAPACITY
            res_50 = check_dep_exists(50)
            if res_50 is True:
                res_max = check_dep_exists(self.max_capacity)
                if res_max is True:
                    return self.max_capacity
                return 50
            low, high = 1, 49

        # 3. Wyszukiwanie binarne
        exact = 1
        while low <= high:
            mid = (low + high) // 2
            res_mid = check_dep_exists(mid)
            if res_mid is None:
                return prev_val if (prev_val and isinstance(prev_val, int)) else exact
            if res_mid is True:
                exact = mid
                low = mid + 1
            else:
                high = mid - 1
            time.sleep(0.01)

        return exact

    def fetch_roundtrip_day(
        self,
        from_key: str,
        to_key: str,
        date_str: str,
        check_seats: bool = False,
        prev_seats_there: Optional[Dict[str, int]] = None,
        prev_seats_return: Optional[Dict[str, int]] = None,
    ) -> Tuple[List[Departure], List[Departure]]:
        """
        Pobiera kursy TAM i POWRÓT na podany dzień (DD.MM.YYYY).
        Jeśli check_seats=True, precyzyjnie mierzy liczbę wolnych miejsc (1..MAX_CAPACITY).
        """
        f_stop = STOPS.get(from_key.lower())
        t_stop = STOPS.get(to_key.lower())
        if not f_stop or not t_stop:
            raise ValueError(f"Nieznany przystanek: {from_key} lub {to_key}")

        there_raw, return_raw = self.query_roundtrip_raw(
            f_stop["id"], f_stop["name"], t_stop["id"], t_stop["name"], date_str, passengers=1
        )
        if not there_raw and not return_raw:
            return [], []

        there_courses: List[Departure] = []
        return_courses: List[Departure] = []

        # Przetwarzanie kursów TAM
        if there_raw:
            for dep, info in there_raw.items():
                seats = 1
                if check_seats:
                    prev_s = prev_seats_there.get(dep) if prev_seats_there else None
                    seats = self._resolve_single_course(
                        f_stop["id"],
                        f_stop["name"],
                        t_stop["id"],
                        t_stop["name"],
                        date_str,
                        dep,
                        direction="THERE",
                        prev_val=prev_s,
                    )

                there_courses.append(
                    Departure(
                        route_id=f"{from_key}_{to_key}_{date_str}_{dep.replace(':', '')}",
                        date=date_str,
                        departure_time=info["dep"],
                        arrival_time=info["arr"],
                        origin=f_stop["name"],
                        destination=t_stop["name"],
                        price=info["price"],
                        free_seats=seats,
                        direction="THERE",
                        is_sold_out=(seats == 0),
                    )
                )

        # Przetwarzanie kursów POWRÓT
        if return_raw:
            for dep, info in return_raw.items():
                seats = 1
                if check_seats:
                    prev_s = prev_seats_return.get(dep) if prev_seats_return else None
                    seats = self._resolve_single_course(
                        f_stop["id"],
                        f_stop["name"],
                        t_stop["id"],
                        t_stop["name"],
                        date_str,
                        dep,
                        direction="RETURN",
                        prev_val=prev_s,
                    )

                return_courses.append(
                    Departure(
                        route_id=f"{to_key}_{from_key}_{date_str}_{dep.replace(':', '')}",
                        date=date_str,
                        departure_time=info["dep"],
                        arrival_time=info["arr"],
                        origin=t_stop["name"],
                        destination=f_stop["name"],
                        price=info["price"],
                        free_seats=seats,
                        direction="RETURN",
                        is_sold_out=(seats == 0),
                    )
                )

        there_courses.sort(key=lambda x: x.departure_time)
        return_courses.sort(key=lambda x: x.departure_time)
        return there_courses, return_courses
