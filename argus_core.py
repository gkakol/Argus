import logging
import random
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
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


@dataclass
class Departure:
    route_id: str
    date: str  # YYYY-MM-DD
    departure_time: str  # HH:MM
    arrival_time: str  # HH:MM
    origin: str
    destination: str
    price: float
    free_seats: int
    is_sold_out: bool
    direction: str  # "THERE" lub "RETURN"

    def to_dict(self) -> dict:
        return asdict(self)


class ArgusCore:
    BASE_URL = "https://neobus.pl/pl"
    STOPS = {
        "SANOK": {"id": "17", "name": "SANOK D.A. Lipińskiego "},
        "NIEBYLEC": {"id": "19", "name": "NIEBYLEC"},
        "WROCLAW": {"id": "77", "name": "WROCŁAW PKS Polbus"},
        "GLIWICE": {
            "id": "123",
            "name": "GLIWICE Centrum Przesiadkowe ul. Składowa 8a",
        },
        "KATOWICE": {"id": "73", "name": "KATOWICE D.A. ul. Sądowa 5"},
        "RZESZOW": {"id": "76", "name": "RZESZÓW D.A. PKS"},
        "KRAKOW": {"id": "71", "name": "KRAKÓW MDA"},
    }

    def __init__(self, timeout: int = 25):
        self.timeout = timeout
        self.session = self._init_session()
        self._warmed_up = False

    def _init_session(self) -> requests.Session:
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        return session

    def _warmup(self):
        """Pobiera stronę główną, aby zainicjalizować sesję i ciasteczka."""
        if not self._warmed_up:
            try:
                headers = {
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Upgrade-Insecure-Requests": "1",
                }
                res = self.session.get(self.BASE_URL, headers=headers, timeout=self.timeout)
                if res.status_code == 200:
                    self._warmed_up = True
                    logger.info("Sesja pomyślnie zainicjalizowana (ciasteczka pobrane).")
                else:
                    logger.warning(f"Warmup status: {res.status_code}")
            except Exception as e:
                logger.error(f"Błąd inicjalizacji sesji: {e}")

    def _post_search(
        self,
        origin_id: str,
        origin_name: str,
        destination_id: str,
        destination_name: str,
        date_str: str,
        passengers: int = 1,
        ticket_type: str = "student",
    ) -> Optional[dict]:
        self._warmup()

        payload = {
            "ajax": "true",
            "dataType": "json",
            "module": "neotickets",
            "step": "1",
            "ticket_type": ticket_type,
            "initial_stop": origin_id,
            "final_stop": destination_id,
            "passengers": str(passengers),
            "date_there": date_str,
            "date_return": date_str,
            "initial_stop_name": origin_name,
            "final_stop_name": destination_name,
        }

        post_headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://neobus.pl",
            "Referer": "https://neobus.pl/pl",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        try:
            response = self.session.post(
                self.BASE_URL,
                data=payload,
                headers=post_headers,
                timeout=self.timeout,
            )
            if response.status_code == 200:
                try:
                    return response.json()
                except Exception as e:
                    logger.error(f"Błąd parsowania JSON: {e} | Treść: {response.text[:200]}")
                    return None

            logger.warning(
                f"HTTP {response.status_code} dla {date_str} | Odpowiedź: {response.text[:300]}"
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Błąd sieci podczas pobierania {date_str}: {e}")
        return None

    @staticmethod
    def _parse_time(item_name: str) -> Tuple[str, str]:
        match = re.search(r"(\d{2})[-:](\d{2})\s*-\s*(\d{2})[:\-](\d{2})", item_name)
        if match:
            dep = f"{match.group(1)}:{match.group(2)}"
            arr = f"{match.group(3)}:{match.group(4)}"
            return dep, arr
        return "--:--", "--:--"

    def fetch_roundtrip_day(
        self,
        origin_key: str,
        destination_key: str,
        target_date: str,
        check_seats: bool = False,
    ) -> Tuple[List[Departure], List[Departure]]:
        orig = self.STOPS.get(origin_key)
        dest = self.STOPS.get(destination_key)

        if not orig or not dest:
            raise ValueError(f"Nieznany przystanek: {origin_key} lub {destination_key}")

        if "-" in target_date:
            dt = datetime.strptime(target_date, "%Y-%m-%d")
            dot_date = dt.strftime("%d.%m.%Y")
            iso_date = target_date
        else:
            dot_date = target_date
            iso_date = datetime.strptime(target_date, "%d.%m.%Y").strftime("%Y-%m-%d")

        logger.info(
            f"Odpytywanie trasy {origin_key} <-> {destination_key} na dzień {dot_date}..."
        )
        time.sleep(random.uniform(0.5, 1.2))

        data = self._post_search(
            orig["id"], orig["name"], dest["id"], dest["name"], dot_date, passengers=1
        )
        if not data or "ga4_data" not in data:
            logger.warning(f"Brak ga4_data w odpowiedzi dla {dot_date}")
            return [], []

        ga4 = data["ga4_data"]
        there_departures: List[Departure] = []
        return_departures: List[Departure] = []

        # 0 = TAM (initial -> final)
        if len(ga4) > 0 and "items" in ga4[0]:
            for item in ga4[0]["items"]:
                dep_time, arr_time = self._parse_time(item["item_name"])
                there_departures.append(
                    Departure(
                        route_id=f"{origin_key}_{destination_key}_{iso_date}_{dep_time.replace(':', '')}",
                        date=iso_date,
                        departure_time=dep_time,
                        arrival_time=arr_time,
                        origin=orig["name"].strip(),
                        destination=dest["name"].strip(),
                        price=float(item.get("price", 0.0)),
                        free_seats=9 if not check_seats else 1,
                        is_sold_out=False,
                        direction="THERE",
                    )
                )

        # 1 = Z POWROTEM (final -> initial)
        if len(ga4) > 1 and "items" in ga4[1]:
            for item in ga4[1]["items"]:
                dep_time, arr_time = self._parse_time(item["item_name"])
                return_departures.append(
                    Departure(
                        route_id=f"{destination_key}_{origin_key}_{iso_date}_{dep_time.replace(':', '')}",
                        date=iso_date,
                        departure_time=dep_time,
                        arrival_time=arr_time,
                        origin=dest["name"].strip(),
                        destination=orig["name"].strip(),
                        price=float(item.get("price", 0.0)),
                        free_seats=9 if not check_seats else 1,
                        is_sold_out=False,
                        direction="RETURN",
                    )
                )

        logger.info(
            f"Pobrano {len(there_departures)} kursów TAM i {len(return_departures)} kursów Z POWROTEM dla {dot_date}"
        )
        return there_departures, return_departures
