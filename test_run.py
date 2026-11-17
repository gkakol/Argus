from datetime import date, timedelta
from argus_core import ArgusCore

def main():
    print(">>> Uruchamianie ArgusCore na GitHub Actions...")
    core = ArgusCore()

    # Sprawdzamy kurs za 5 dni od dzisiaj
    test_date = (date.today() + timedelta(days=5)).strftime("%d.%m.%Y")
    print(f">>> Sprawdzam trasę: Wrocław -> Sanok na dzień {test_date}...")

    kursy = core.fetch_route_day("wroclaw", "sanok", test_date, check_seats=False)
    
    print("\n" + "=" * 50)
    print(f"WYNIK: Znaleziono {len(kursy)} kursów!")
    print("=" * 50)
    for k in kursy:
        print(f"  Odjazd: {k.departure_time} -> Przyjazd: {k.arrival_time} | Cena: {k.price:.2f} PLN")
    print("=" * 50)

if __name__ == "__main__":
    main()
