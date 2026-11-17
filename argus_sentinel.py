import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple
import requests

from argus_core import ArgusCore, Departure

# =====================================================================
#                        KONFIGURACJA SENTINELA
# =====================================================================

PARALLEL_WORKERS = 4
MAX_CAPACITY = 70
SUPER_PROMO_PRICE = 35.00  # Próg natychmiastowego powiadomienia promo
TARGET_PROMO_PRICE = 50.00

DATA_DIR = "data"
HORIZON_FILE = os.path.join(DATA_DIR, "horizon_boundary.txt")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# 9 zdefiniowanych relacji bazowych (Argus automatycznie bada obie strony relacji)
TARGET_ROUTES = [
    # Warszawa
    ("warszawa", "sanok"),
    ("warszawa", "krosno"),
    ("warszawa", "przemysl"),
    # Wrocław
    ("wroclaw", "sanok"),
    ("wroclaw", "krosno"),
    ("wroclaw", "przemysl"),
    # Łódź
    ("lodz", "sanok"),
    ("lodz", "krosno"),
    ("lodz", "przemysl"),
]

class ArgusSentinel:
    def __init__(self):
        self.core = ArgusCore(max_capacity=MAX_CAPACITY, data_dir=DATA_DIR)
        os.makedirs(DATA_DIR, exist_ok=True)

    # =====================================================================
    #                  1. RADAR HORYZONTU SPRZEDAŻY
    # =====================================================================

    def detect_sales_horizon(self, prev_furthest: str = "") -> Tuple[str, int]:
        """
        Wykładnicze poszukiwanie krańca kalendarza za pomocą binarnego wyszukiwania.
        Zwraca: (data_ostatniego_dnia_str, łączna_liczba_dni_do_przeskanowania).
        """
        today = date.today()
        anchor = today + timedelta(days=30)
        if prev_furthest:
            try:
                p_dt = datetime.strptime(prev_furthest, "%d.%m.%Y").date()
                if p_dt >= today:
                    anchor = p_dt
            except ValueError:
                pass

        # 1. Sprawdzamy czy w punkcie kotwicy są jakiekolwiek kursy na trasie Wrocław <-> Sanok
        t_base, r_base = self.core.query_roundtrip_raw(
            self.core.resolve_stop("wroclaw")["id"],
            self.core.resolve_stop("wroclaw")["name"],
            self.core.resolve_stop("sanok")["id"],
            self.core.resolve_stop("sanok")["name"],
            anchor.strftime("%d.%m.%Y"),
            passengers=1,
        )

        if not t_base and not r_base:
            low_days = 1
            high_days = max(1, (anchor - today).days)
        else:
            low_days = (anchor - today).days
            step = 7
            curr_probe = anchor
            while True:
                probe_d = curr_probe + timedelta(days=step)
                t_p, r_p = self.core.query_roundtrip_raw(
                    self.core.resolve_stop("wroclaw")["id"],
                    self.core.resolve_stop("wroclaw")["name"],
                    self.core.resolve_stop("sanok")["id"],
                    self.core.resolve_stop("sanok")["name"],
                    probe_d.strftime("%d.%m.%Y"),
                    passengers=1,
                )
                time.sleep(0.04)
                if t_p or r_p:
                    curr_probe = probe_d
                    low_days = (curr_probe - today).days
                    step *= 2
                else:
                    high_days = (probe_d - today).days
                    break

        # 2. Binary search dla dokładnego krańca
        last_valid_day = today + timedelta(days=low_days)
        low, high = low_days, high_days

        while low <= high:
            mid = (low + high) // 2
            d_mid = today + timedelta(days=mid)
            t_m, r_m = self.core.query_roundtrip_raw(
                self.core.resolve_stop("wroclaw")["id"],
                self.core.resolve_stop("wroclaw")["name"],
                self.core.resolve_stop("sanok")["id"],
                self.core.resolve_stop("sanok")["name"],
                d_mid.strftime("%d.%m.%Y"),
                passengers=1,
            )
            time.sleep(0.02)
            if t_m or r_m:
                last_valid_day = d_mid
                low = mid + 1
            else:
                high = mid - 1

        total_days = max(1, (last_valid_day - today).days + 1)
        return last_valid_day.strftime("%d.%m.%Y"), total_days

    def check_and_notify_horizon(self, new_furthest: str):
        """Wysyła alert na Discorda, jeśli horyzont sprzedaży wydłużył się o >= 3 dni."""
        if not new_furthest:
            return

        prev = ""
        if os.path.isfile(HORIZON_FILE):
            try:
                with open(HORIZON_FILE, "r", encoding="utf-8") as f:
                    prev = f.read().strip()
            except Exception:
                pass

        if not prev:
            with open(HORIZON_FILE, "w", encoding="utf-8") as f:
                f.write(new_furthest)
            return

        try:
            d_new = datetime.strptime(new_furthest, "%d.%m.%Y").date()
            d_prev = datetime.strptime(prev, "%d.%m.%Y").date()

            diff_days = (d_new - d_prev).days
            if diff_days >= 3:
                msg = (
                    f"📢 **OTWARTO NOWĄ PULĘ BILETÓW!** @everyone\n\n"
                    f"📅 Sprzedaż wydłużona do: **{new_furthest}** (wcześniej: `{prev}`, **+{diff_days} dni**)\n"
                    f"🔗 Sprawdź bilety na: https://neobus.pl/"
                )
                self.send_discord_alerts([msg])
                with open(HORIZON_FILE, "w", encoding="utf-8") as f:
                    f.write(new_furthest)
            elif d_new > d_prev:
                with open(HORIZON_FILE, "w", encoding="utf-8") as f:
                    f.write(new_furthest)
        except Exception as e:
            print(f"[WARN] Błąd sprawdzania horyzontu: {e}")

    # =====================================================================
    #               2. ANALIZA ZMIAN I POWIADOMIENIA (DELTY)
    # =====================================================================

    def compute_deltas_and_alerts(
        self,
        current_courses: List[Departure],
        prev_dict: Dict[Tuple[str, str], dict],
        now_ts: str,
    ) -> List[str]:
        alerts = []
        now_dt = datetime.strptime(now_ts, "%Y-%m-%d %H:%M:%S")

        for c in current_courses:
            prev = prev_dict.get((c.date, c.departure_time))
            if not prev:
                # Nowo wykryty kurs w niskiej cenie
                if c.price <= SUPER_PROMO_PRICE:
                    alerts.append(
                        f"🔥 **NOWY KURS W SUPER CENIE!**\n"
                        f"🚌 **{c.origin} ➔ {c.destination}**\n"
                        f"📅 Data: `{c.date}` | ⏰ `{c.departure_time} -> {c.arrival_time}`\n"
                        f"💰 Cena: **{c.price:.2f} zł** | Miejsca: `{c.free_seats} szt.`"
                    )
                continue

            prev_price = prev.get("price", 0.0)
            prev_seats = prev.get("seats", -1)

            # 1. Wykrywanie obniżki ceny
            if prev_price > 0 and c.price < prev_price:
                diff = prev_price - c.price
                alerts.append(
                    f"🟢 **OBNIŻKA CENY!** (-{diff:.2f} zł)\n"
                    f"🚌 **{c.origin} ➔ {c.destination}**\n"
                    f"📅 `{c.date}` | ⏰ `{c.departure_time}`\n"
                    f"📉 Stara cena: ~~{prev_price:.2f} zł~~ ➔ Nowa: **{c.price:.2f} zł**\n"
                    f"💺 Wolne miejsca: `{c.free_seats} szt.`"
                )

            # 2. Wykrywanie wejścia w Super Promo (<= 35 zł)
            if c.price <= SUPER_PROMO_PRICE < prev_price:
                alerts.append(
                    f"🔥 **SUPER PROMO!** {c.origin} ➔ {c.destination} | `{c.date}` {c.departure_time} ➔ **{c.price:.2f} zł**!"
                )

            # 3. Wykrywanie krytycznej końcówki na weekend (piątek / niedziela)
            try:
                weekday = datetime.strptime(c.date, "%d.%m.%Y").weekday()
                if weekday in [4, 6] and c.free_seats <= 5 and prev_seats > 5:
                    alerts.append(
                        f"⚠️ **KOŃCÓWKA NA WEEKEND!**\n"
                        f"🚌 **{c.origin} ➔ {c.destination}**\n"
                        f"📅 `{c.date}` ({c.departure_time}) ➔ Zostało tylko **{c.free_seats} miejsc**!"
                    )
            except Exception:
                pass

            # 4. Wykrywanie zwrotu biletów (liczba foteli wzrosła na prawie wyprzedany kurs)
            if 0 < prev_seats <= 3 and c.free_seats > prev_seats:
                diff_s = c.free_seats - prev_seats
                alerts.append(
                    f"🎟️ **ZWROT BILETÓW!**\n"
                    f"🚌 **{c.origin} ➔ {c.destination}**\n"
                    f"📅 `{c.date}` {c.departure_time} ➔ Ktoś zwrócił **+{diff_s} szt.** (dostępne: `{c.free_seats}`)"
                )

        return alerts

    def send_discord_alerts(self, alerts: List[str]):
        if not DISCORD_WEBHOOK_URL or not alerts:
            return

        for chunk in [alerts[i:i + 4] for i in range(0, len(alerts), 4)]:
            body = "\n\n".join(chunk)
            try:
                requests.post(
                    DISCORD_WEBHOOK_URL,
                    json={"username": "Argus Radar", "content": body},
                    timeout=8,
                )
            except Exception as e:
                print(f"[WARN] Błąd wysyłki na Discorda: {e}")

    # =====================================================================
    #                     3. ORKIESTRACJA SKANOWANIA
    # =====================================================================

    def scan_route_pair(
        self,
        origin: str,
        dest: str,
        dates: List[str],
        now_ts: str,
    ) -> List[str]:
        """Przetwarza kompletną relację dwukierunkową przez wszystkie zadane daty."""
        csv_there = self.core.get_csv_filename(origin, dest)
        csv_return = self.core.get_csv_filename(dest, origin)

        snap_there = self.core.load_previous_snapshot(csv_there)
        snap_return = self.core.load_previous_snapshot(csv_return)

        combined_prev = {**snap_there, **snap_return}

        collected_there: List[Departure] = []
        collected_return: List[Departure] = []

        # Skanowanie dat dla danej pary miast
        for d in dates:
            time.sleep(0.04)
            t_courses, r_courses = self.core.fetch_roundtrip_day(
                origin, dest, d, check_seats=True, prev_snapshot=combined_prev
            )
            collected_there.extend(t_courses)
            collected_return.extend(r_courses)

        # Analiza zdarzeń i generowanie alertów
        alerts_there = self.compute_deltas_and_alerts(collected_there, snap_there, now_ts)
        alerts_return = self.compute_deltas_and_alerts(collected_return, snap_return, now_ts)

        # Zapis i deduplikacja w CSV
        self.core.save_and_rotate_csv(csv_there, collected_there)
        self.core.save_and_rotate_csv(csv_return, collected_return)

        return alerts_there + alerts_return

    def run(self):
        start_time = time.time()
        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print("=" * 65)
        print("👁️ ARGUS SENTINEL: AUTONOMICZNY RADAR MULTI-TRASA")
        print(f"🕒 Czas rozpoczęcia: {now_ts}")
        print("=" * 65)

        # Krok 1: Sprawdzenie horyzontu sprzedaży
        print("\n🔍 [1/3] Sprawdzanie aktywnego horyzontu sprzedaży...")
        prev_h = ""
        if os.path.isfile(HORIZON_FILE):
            try:
                with open(HORIZON_FILE, "r", encoding="utf-8") as f:
                    prev_h = f.read().strip()
            except Exception:
                pass

        furthest_date, total_days = self.detect_sales_horizon(prev_h)
        print(f"✅ Horyzont: {furthest_date} ({total_days} dni w kalendarzu)")
        self.check_and_notify_horizon(furthest_date)

        # Generujemy listę dat do monitorowania
        dates_to_scan = [
            (date.today() + timedelta(days=i)).strftime("%d.%m.%Y")
            for i in range(total_days)
        ]

        print(f"\n📡 [2/3] Skanowanie {len(TARGET_ROUTES)} tras wielowątkowo ({PARALLEL_WORKERS} workers)...")

        all_alerts = []
        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
            futures = {
                executor.submit(
                    self.scan_route_pair, orig, dst, dates_to_scan, now_ts
                ): (orig, dst)
                for orig, dst in TARGET_ROUTES
            }

            for fut in as_completed(futures):
                orig, dst = futures[fut]
                try:
                    route_alerts = fut.result()
                    all_alerts.extend(route_alerts)
                    print(f"  ✅ Zakończono: {orig.upper()} <-> {dst.upper()} (Alerty: {len(route_alerts)})")
                except Exception as e:
                    print(f"  ❌ Błąd skanowania {orig} <-> {dst}: {e}")

        # Krok 3: Wysyłka alertów na Discorda
        print(f"\n📢 [3/3] Podsumowanie alertów: {len(all_alerts)} zdarzeń.")
        if all_alerts:
            self.send_discord_alerts(all_alerts)
            print("  🚀 Alerty zostały pomyślnie wysłane na Discorda!")
        else:
            print("  ℹ️ Brak nowych zdarzeń alertowych w tym cyklu.")

        elapsed = time.time() - start_time
        print("\n" + "=" * 65)
        print(f"⏱️ CAŁOŚĆ WYKONANA W CZASIE: {elapsed:.2f} s")
        print("=" * 65)


if __name__ == "__main__":
    sentinel = ArgusSentinel()
    sentinel.run()
