import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import json
import logging
import os
import re
import threading
import time
from typing import Dict, List, Optional, Set, Tuple, Union
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

ALL_STOPS = {
    "babica_kolonia": {"id": "49", "name": "BABICA Kolonia"},
    "blizne": {"id": "46", "name": "BLIZNE"},
    "boguchwala": {"id": "36", "name": "BOGUCHWAŁA ODR"},
    "brzozow": {"id": "44", "name": "BRZOZÓW Dworzec PKS Plac Grunwaldzki 01"},
    "busko_zdroj": {"id": "84", "name": "BUSKO- ZDRÓJ MDA ul. Waryńskiego 29"},
    "domaradz": {"id": "47", "name": "DOMARADZ"},
    "gliwice": {"id": "123", "name": "GLIWICE Centrum Przesiadkowe ul. Składowa 8a"},
    "grabownica": {"id": "38", "name": "GRABOWNICA"},
    "humniska": {"id": "43", "name": "HUMNISKA"},
    "iwonicz_zdroj": {"id": "21", "name": "IWONICZ Zdrój"},
    "ilza": {"id": "124", "name": "IŁŻA D.A. ul. Podzamcze 33"},
    "jaroslaw": {"id": "94", "name": "JAROSŁAW Centr. Przes. PKP"},
    "katowice": {"id": "73", "name": "KATOWICE D.A. ul. Sądowa 5"},
    "kielce": {"id": "85", "name": "KIELCE DA ul. Czarnowska 12"},
    "kolbuszowa": {"id": "23", "name": "KOLBUSZOWA Dw. PKS"},
    "krakow_balice": {"id": "72", "name": "KRAKÓW Lotnisko Balice"},
    "krakow": {"id": "71", "name": "KRAKÓW MDA"},
    "krosno": {"id": "22", "name": "KROSNO D.A.st. 4"},
    "lesko": {"id": "66", "name": "LESKO D.A. ul. Piłsudskiego 50"},
    "lutcza": {"id": "48", "name": "LUTCZA skrz."},
    "medyka": {"id": "96", "name": "MEDYKA Granica"},
    "miejsce_piastowe": {"id": "37", "name": "MIEJSCE PIASTOWE"},
    "mielec": {"id": "81", "name": "MIELEC D.A. ul Jagiellończyka"},
    "niebylec": {"id": "19", "name": "NIEBYLEC"},
    "nowa_deba": {"id": "25", "name": "NOWA DĘBA"},
    "opatow": {"id": "35", "name": "OPATÓW D.A. ul. Sienkiewicza 19"},
    "ostrowiec_sw": {"id": "78", "name": "OSTROWIEC Św. D.A."},
    "piotrkow_tryb": {"id": "92", "name": "PIOTRKÓW TRYB. DA ul.P.O.W. 12"},
    "polanczyk": {"id": "62", "name": "POLAŃCZYK"},
    "polanczyk_skrz": {"id": "63", "name": "POLAŃCZYK skrz."},
    "polaniec": {"id": "82", "name": "POŁANIEC D.A. (Galeria Połaniecka)"},
    "przemysl": {"id": "95", "name": "PRZEMYŚL Dw.PKS"},
    "radom_idalska": {"id": "54", "name": "RADOM Słowackiego/Idalińska"},
    "radom": {"id": "55", "name": "RADOM Warszawska (rondo)"},
    "rymanow": {"id": "24", "name": "RYMANÓW Rynek"},
    "rymanow_zdroj": {"id": "29", "name": "RYMANÓW Zdrój Góra"},
    "rzeszow": {"id": "76", "name": "RZESZÓW D.A. PKS"},
    "sanok": {"id": "17", "name": "SANOK D.A. Lipińskiego"},
    "solina": {"id": "64", "name": "SOLINA"},
    "stara_wies": {"id": "39", "name": "STARA WIEŚ,"},
    "staszow": {"id": "83", "name": "STASZÓW Rynek 01/02"},
    "tarnobrzeg": {"id": "79", "name": "TARNOBRZEG D.A."},
    "warszawa": {"id": "75", "name": "WARSZAWA Dw. Zach. st.7"},
    "warszawa_chopin": {"id": "28", "name": "WARSZAWA Lotn. Chopina"},
    "wroclaw": {"id": "77", "name": "WROCŁAW PKS Polbus"},
    "zagorz": {"id": "68", "name": "ZAGÓRZ osiedle"},
    "zarnow": {"id": "115", "name": "ŻARNÓW Pl.Piłsudskiego/Rynek"},
    "lodz_fabryczna": {"id": "93", "name": "ŁÓDŹ FABRYCZNA WPA"},
    "lodz": {"id": "88", "name": "ŁÓDŹ KALISKA Włókniarzy/Karolewska"},
    "loniow": {"id": "53", "name": "ŁONIÓW"},
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
    def __init__(self, max_capacity: int = 70, archive_dir: str = "archive"):
        self.max_capacity = max_capacity
        self.archive_dir = archive_dir
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
    def _normalize_string(text: str) -> str:
        replacements = {
            "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
            "ó": "o", "ś": "s", "ź": "z", "ż": "z",
            " ": "_", "-": "_", ".": ""
        }
        low = text.lower().strip()
        for k, v in replacements.items():
            low = low.replace(k, v)
        return low

    def resolve_stop(self, stop_query: str) -> dict:
        norm_query = self._normalize_string(stop_query)
        if norm_query in ALL_STOPS:
            return ALL_STOPS[norm_query]
        for key, data in ALL_STOPS.items():
            if norm_query == key or key.startswith(norm_query) or norm_query in key:
                return data
        for data in ALL_STOPS.values():
            if norm_query in self._normalize_string(data["name"]):
                return data
        raise ValueError(f"Nie znaleziono przystanku dla: '{stop_query}'.")

    @staticmethod
    def normalize_date(target_date: Union[str, date, datetime]) -> str:
        if isinstance(target_date, (date, datetime)):
            return target_date.strftime("%d.%m.%Y")
        target_date = target_date.strip()
        if "-" in target_date:
            dt = datetime.strptime(target_date, "%Y-%m-%d")
            return dt.strftime("%d.%m.%Y")
        return target_date

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
                    time.sleep(0.08)
                    continue

                raw = r.json() if hasattr(r, "json") else json.loads(r.text)
                content = raw.get("neotickets", raw) if isinstance(raw, dict) else raw
                data = json.loads(content) if isinstance(content, str) else content
                if isinstance(data, dict):
                    return data
            except Exception:
                time.sleep(0.08)
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

    # =====================================================================
    #               WARSTWA PAMIĘCI I BAZY DANYCH (CSV)
    # =====================================================================

    def get_csv_filename(self, origin: str, destination: str) -> str:
        """Generuje standardową nazwę pliku, np. 'ceny_wroclaw_sanok.csv'."""
        f_key = self._normalize_string(self.resolve_stop(origin)["name"].split()[0])
        t_key = self._normalize_string(self.resolve_stop(destination)["name"].split()[0])
        return f"ceny_{f_key}_{t_key}.csv"

    def load_previous_snapshot(self, csv_file: str) -> Dict[Tuple[str, str], int]:
        """
        Wczytuje z pliku CSV ostatnie znane stany wolnych miejsc:
        Zwraca mapę: {(date_str, dep_time): free_seats}
        """
        prev_map = {}
        if not os.path.isfile(csv_file):
            return prev_map
        try:
            with open(csv_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    d = row.get("Data kursu")
                    h = row.get("Godzina")
                    s = row.get("Wolne miejsca")
                    if d and h and s and s.isdigit():
                        prev_map[(d, h)] = int(s)
        except Exception as e:
            logger.debug(f"Brak lub błąd odczytu {csv_file}: {e}")
        return prev_map

    def save_and_rotate_csv(self, csv_file: str, courses: List[Departure]):
        """
        Zapisuje nowe pomiary do bazy CSV oraz automatycznie przenosi
        przeszłe kursy do archiwum (archive/arch_*.csv).
        """
        if not courses:
            return

        today = date.today()
        ts_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        existing_rows = []
        if os.path.isfile(csv_file):
            try:
                with open(csv_file, "r", encoding="utf-8") as f:
                    existing_rows = list(csv.DictReader(f))
            except Exception:
                existing_rows = []

        new_rows = [
            {
                "Data pomiaru": ts_now,
                "Data kursu": c.date,
                "Godzina": c.departure_time,
                "Cena (PLN)": f"{c.price:.2f}",
                "Wolne miejsca": str(c.free_seats),
            }
            for c in courses
        ]

        combined = existing_rows + new_rows
        active_rows = []
        archive_rows = []

        for r in combined:
            try:
                d_kurs = datetime.strptime(r["Data kursu"], "%d.%m.%Y").date()
                if d_kurs >= today:
                    active_rows.append(r)
                else:
                    archive_rows.append(r)
            except Exception:
                active_rows.append(r)

        # Zapis do archiwum
        if archive_rows:
            os.makedirs(self.archive_dir, exist_ok=True)
            arch_file = os.path.join(self.archive_dir, f"arch_{os.path.basename(csv_file)}")
            file_exists = os.path.isfile(arch_file)
            with open(arch_file, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=["Data pomiaru", "Data kursu", "Godzina", "Cena (PLN)", "Wolne miejsca"]
                )
                if not file_exists:
                    writer.writeheader()
                writer.writerows(archive_rows)

        # Nadpisanie pliku aktywnego
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["Data pomiaru", "Data kursu", "Godzina", "Cena (PLN)", "Wolne miejsca"]
            )
            writer.writeheader()
            writer.writerows(active_rows)

    # =====================================================================
    #               GŁÓWNA METODA Z ADAPTACYJNYM WARM-START
    # =====================================================================

    def fetch_roundtrip_day(
        self,
        origin: str,
        destination: str,
        target_date: Union[str, date, datetime],
        check_seats: bool = True,
        prev_snapshot: Optional[Dict[Tuple[str, str], int]] = None,
    ) -> Tuple[List[Departure], List[Departure]]:
        """
        Pobiera kursy TAM i POWRÓT. 
        Jeśli przekazano prev_snapshot, używa Warm-Startu drastycznie redukując zapytania HTTP.
        """
        f_stop = self.resolve_stop(origin)
        t_stop = self.resolve_stop(destination)
        date_str = self.normalize_date(target_date)

        logger.info(f"Odpytywanie {f_stop['name']} <-> {t_stop['name']} na {date_str}...")

        there_base, return_base = self.query_roundtrip_raw(
            f_stop["id"], f_stop["name"], t_stop["id"], t_stop["name"], date_str, passengers=1
        )
        if not there_base and not return_base:
            return [], []

        all_courses = []
        for dep, info in (there_base or {}).items():
            prev_s = prev_snapshot.get((date_str, dep)) if prev_snapshot else None
            all_courses.append({
                "dep": dep, "info": info, "direction": "THERE",
                "low": 1, "high": self.max_capacity, "exact": 1,
                "prev_val": prev_s
            })
        for dep, info in (return_base or {}).items():
            prev_s = prev_snapshot.get((date_str, dep)) if prev_snapshot else None
            all_courses.append({
                "dep": dep, "info": info, "direction": "RETURN",
                "low": 1, "high": self.max_capacity, "exact": 1,
                "prev_val": prev_s
            })

        if check_seats and all_courses:
            cache = {1: (set(there_base.keys()), set(return_base.keys()))}

            # 1. Warm-Start: sprawdzamy zapamiętane wartości z bazy danych
            warm_probes = set()
            for c in all_courses:
                if c["prev_val"] and isinstance(c["prev_val"], int) and 1 < c["prev_val"] <= self.max_capacity:
                    warm_probes.add(c["prev_val"])
                    if c["prev_val"] < self.max_capacity:
                        warm_probes.add(min(self.max_capacity, c["prev_val"] + 2))

            for probe in sorted(warm_probes, reverse=True):
                t_map, r_map = self.query_roundtrip_raw(
                    f_stop["id"], f_stop["name"], t_stop["id"], t_stop["name"], date_str, probe
                )
                if t_map is not None:
                    cache[probe] = (set(t_map.keys()), set(r_map.keys()))
                    for c in all_courses:
                        if c["prev_val"] == probe or (c["prev_val"] and probe == c["prev_val"] + 2):
                            active = cache[probe][0] if c["direction"] == "THERE" else cache[probe][1]
                            if c["dep"] in active:
                                c["low"] = probe
                                c["exact"] = max(c["exact"], probe)
                            else:
                                c["high"] = min(c["high"], probe - 1)

            # 2. Sonda na 50 i MAX_CAPACITY dla pozostałych
            remaining = [c for c in all_courses if c["low"] < c["high"]]
            if remaining:
                for probe in [self.max_capacity, 50]:
                    if probe not in cache:
                        t_map, r_map = self.query_roundtrip_raw(
                            f_stop["id"], f_stop["name"], t_stop["id"], t_stop["name"], date_str, probe
                        )
                        if t_map is not None:
                            cache[probe] = (set(t_map.keys()), set(r_map.keys()))

                    if probe in cache:
                        for c in all_courses:
                            active = cache[probe][0] if c["direction"] == "THERE" else cache[probe][1]
                            if c["dep"] in active:
                                c["low"] = probe
                                c["exact"] = max(c["exact"], probe)
                            else:
                                c["high"] = min(c["high"], probe - 1)

            # 3. Klasyczny binary search dla nierozstrzygniętych
            while True:
                pending = [c for c in all_courses if c["low"] < c["high"]]
                if not pending:
                    break

                mid = (pending[0]["low"] + pending[0]["high"]) // 2

                if mid not in cache:
                    t_map, r_map = self.query_roundtrip_raw(
                        f_stop["id"], f_stop["name"], t_stop["id"], t_stop["name"], date_str, mid
                    )
                    if t_map is None:
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

        there_courses: List[Departure] = []
        return_courses: List[Departure] = []

        for c in all_courses:
            is_there = (c["direction"] == "THERE")
            orig_name = f_stop["name"] if is_there else t_stop["name"]
            dest_name = t_stop["name"] if is_there else f_stop["name"]
            route_slug = f"{self._normalize_string(origin)}_{self._normalize_string(destination)}" if is_there else f"{self._normalize_string(destination)}_{self._normalize_string(origin)}"

            dep_obj = Departure(
                route_id=f"{route_slug}_{date_str}_{c['dep'].replace(':', '')}",
                date=date_str,
                departure_time=c["info"]["dep"],
                arrival_time=c["info"]["arr"],
                origin=orig_name,
                destination=dest_name,
                price=c["info"]["price"],
                free_seats=c["exact"],
                direction=c["direction"],
                is_sold_out=(c["exact"] == 0),
            )
            if is_there:
                there_courses.append(dep_obj)
            else:
                return_courses.append(dep_obj)

        there_courses.sort(key=lambda x: x.departure_time)
        return_courses.sort(key=lambda x: x.departure_time)
        return there_courses, return_courses
