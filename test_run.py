import time
from argus_core import ArgusCore

def main():
    print(">>> Uruchamianie ArgusCore (Test: Warm-Start + Zapis CSV + Rotacja)...")
    core = ArgusCore(max_capacity=70)
    data_badania = "25.11.2026"
    origin = "Gliwice"
    dest = "Domaradz"

    # Pliki CSV dla relacji TAM i POWRÓT
    csv_tam = core.get_csv_filename(origin, dest)       # ceny_wroclaw_krosno.csv
    csv_powrot = core.get_csv_filename(dest, origin)    # ceny_krosno_wroclaw.csv

    # Wczytanie poprzednich stanów (jeśli pliki już istnieją)
    prev_snapshot = core.load_previous_snapshot(csv_tam)
    prev_snapshot.update(core.load_previous_snapshot(csv_powrot))
    print(f">>> Załadowano {len(prev_snapshot)} historycznych wpisów z bazy CSV.")

    start_t = time.time()
    tam, powrot = core.fetch_roundtrip_day(
        origin, dest, data_badania, check_seats=True, prev_snapshot=prev_snapshot
    )
    elapsed = time.time() - start_t

    print(f"\n⏱️ Czas wykonania pomiaru: {elapsed:.2f} s")
    print(f"🚌 Znaleziono: {len(tam)} kursów TAM i {len(powrot)} kursów POWRÓT.")

    # Zapis i rotacja bazy CSV
    core.save_and_rotate_csv(csv_tam, tam)
    core.save_and_rotate_csv(csv_powrot, powrot)
    print(f"💾 Pomyślnie zaktualizowano pliki: {csv_tam} oraz {csv_powrot}")

if __name__ == "__main__":
    main()
