from argus_core import ArgusCore

def main():
    print(">>> Uruchamianie ArgusCore (Test wykrywania wolnych miejsc)...")
    core = ArgusCore(max_capacity=70)

    test_date = "25.11.2026"
    print(f">>> Analizuję trasę Wrocław <-> Sanok na dzień {test_date} (check_seats=True)...")

    tam, powrot = core.fetch_roundtrip_day(
        "wroclaw", "sanok", test_date, check_seats=True
    )

    print("\n" + "=" * 65)
    print(f"🚌 KIERUNEK TAM: Wrocław -> Sanok (kursów: {len(tam)})")
    print("=" * 65)
    for k in tam:
        print(
            f"  Odjazd: {k.departure_time} -> {k.arrival_time} | "
            f"Cena: {k.price:6.2f} PLN | "
            f"Wolne fotele: {k.free_seats:2d} szt."
        )

    print("\n" + "=" * 65)
    print(f"🚌 KIERUNEK POWRÓT: Sanok -> Wrocław (kursów: {len(powrot)})")
    print("=" * 65)
    for k in powrot:
        print(
            f"  Odjazd: {k.departure_time} -> {k.arrival_time} | "
            f"Cena: {k.price:6.2f} PLN | "
            f"Wolne fotele: {k.free_seats:2d} szt."
        )
    print("=" * 65)

if __name__ == "__main__":
    main()
