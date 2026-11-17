from argus_core import ArgusCore

def main():
    print(">>> Uruchamianie ArgusCore (Roundtrip Test) na GitHub Actions...")
    core = ArgusCore()

    test_date = "25.11.2026"
    print(f">>> Sprawdzam kursy w obu kierunkach na dzień {test_date}...")

    tam, powrot = core.fetch_roundtrip_day("wroclaw", "sanok", test_date)

    print("\n" + "=" * 60)
    print(f"🚌 KIERUNEK TAM: Wrocław -> Sanok (znaleziono: {len(tam)})")
    print("=" * 60)
    for k in tam:
        print(f"  Odjazd: {k.departure_time} -> Przyjazd: {k.arrival_time} | Cena: {k.price:.2f} PLN | ID: {k.route_id}")

    print("\n" + "=" * 60)
    print(f"🚌 KIERUNEK POWRÓT: Sanok -> Wrocław (znaleziono: {len(powrot)})")
    print("=" * 60)
    for k in powrot:
        print(f"  Odjazd: {k.departure_time} -> Przyjazd: {k.arrival_time} | Cena: {k.price:.2f} PLN | ID: {k.route_id}")
    print("=" * 60)

if __name__ == "__main__":
    main()
