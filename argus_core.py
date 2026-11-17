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

    def _parse_ga4_item_list(self, items: list) -> Dict[str, dict]:
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

    def fetch_roundtrip_day(
        self,
        from_key: str,
        to_key: str,
        date_str: str,
        passengers: int = 1,
    ) -> Tuple[List[Departure], List[Departure]]:
        """
        Pobiera kursy TAM i Z POWROTEM w jednym żądaniu HTTP.
        Zwraca: (lista_kursow_tam, lista_kursow_powrot)
        """
        f_stop = STOPS.get(from_key.lower())
        t_stop = STOPS.get(to_key.lower())
        if not f_stop or not t_stop:
            raise ValueError(f"Nieznany przystanek: {from_key} lub {to_key}")

        payload = {
            "ajax": "true",
            "dataType": "json",
            "module": "neotickets",
            "step": "1",
            "ticket_type": "normal",
            "initial_stop": str(f_stop["id"]),
            "final_stop": str(t_stop["id"]),
            "passengers": str(passengers),
            "date_there": date_str,
            "date_return": date_str,  # Ten sam dzień dla obu stron
            "initial_stop_name": f_stop["name"],
            "final_stop_name": t_stop["name"],
        }

        data = self._execute_post(payload)
        if not data or "ga4_data" not in data or len(data["ga4_data"]) == 0:
            return [], []

        ga4 = data["ga4_data"]
        there_courses: List[Departure] = []
        return_courses: List[Departure] = []

        # 1. Kierunek TAM (ga4_data[0])
        if len(ga4) > 0 and "items" in ga4[0]:
            parsed_there = self._parse_ga4_item_list(ga4[0].get("items", []))
            for dep, info in parsed_there.items():
                there_courses.append(
                    Departure(
                        route_id=f"{from_key}_{to_key}_{date_str}_{dep.replace(':', '')}",
                        date=date_str,
                        departure_time=info["dep"],
                        arrival_time=info["arr"],
                        origin=f_stop["name"],
                        destination=t_stop["name"],
                        price=info["price"],
                        free_seats=9,
                        direction="THERE",
                    )
                )

        # 2. Kierunek POWRÓT (ga4_data[1])
        if len(ga4) > 1 and "items" in ga4[1]:
            parsed_return = self._parse_ga4_item_list(ga4[1].get("items", []))
            for dep, info in parsed_return.items():
                return_courses.append(
                    Departure(
                        route_id=f"{to_key}_{from_key}_{date_str}_{dep.replace(':', '')}",
                        date=date_str,
                        departure_time=info["dep"],
                        arrival_time=info["arr"],
                        origin=t_stop["name"],
                        destination=f_stop["name"],
                        price=info["price"],
                        free_seats=9,
                        direction="RETURN",
                    )
                )

        there_courses.sort(key=lambda x: x.departure_time)
        return_courses.sort(key=lambda x: x.departure_time)
        return there_courses, return_courses
