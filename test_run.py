from argus_core import ArgusCore

def test_route(core: ArgusCore, origin: str, destination: str, target_date: str):
    print("\n" + "=" * 65)
    print(f"🚀 TESTOWANIE RELACJI: {origin.upper()} <---> {destination.upper()} ({target_date})")
    print("=" * 65)

    tam, powrot = core.fetch_roundtrip_day(origin, destination, target_date, check_seats=True)

    print(f"\n🚌 TAM ({origin} -> {destination}) | Kursów: {len(tam)}")
    for k in tam:
        print(f"  [{k.departure_time} -> {k.arrival_time}] {k.price:6.2f} zł | Miejsca: {k.free_seats:2d} | {k.origin} -> {k.destination}")

    print(f"\n🚌 POWRÓT ({destination} -> {origin}) | Kursów: {len(powrot)}")
    for k in powrot:
        print(f"  [{k.departure_time} -> {k.arrival_time}] {k.price:6.2f} zł | Miejsca: {k.free_seats:2d} | {k.origin} -> {k.destination}")

def main():
    core = ArgusCore(max_capacity=70)
    data_badania = "25.11.2026"

    # Test 1: Wrocław <-> Krosno
    test_route(core, "Wrocław", "Krosno", data_badania)

    # Test 2: Warszawa <-> Sanok
    test_route(core, "Warszawa", "Sanok", data_badania)

    # Test 3: Łódź <-> Sanok
    test_route(core, "Łódź", "Sanok", data_badania)

if __name__ == "__main__":
    main()
