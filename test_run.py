import json
from argus_core import ArgusCore

def main():
    print("Inicjalizacja ArgusCore...")
    core = ArgusCore()
    
    # Testujemy relację Wrocław <-> Sanok na 25.11.2026
    test_date = "25.11.2026"
    print(f"Wysyłam zapytanie o trasę WROCLAW <-> SANOK na dzień {test_date}...")
    
    # check_seats=False dla szybkiego testu jednego requestu
    tam, powrot = core.fetch_roundtrip_day("WROCLAW", "SANOK", test_date, check_seats=False)
    
    print("\n" + "=" * 50)
    print(f"KIERUNEK TAM: Wrocław -> Sanok (znaleziono: {len(tam)})")
    print("=" * 50)
    for k in tam:
        print(f"Odjazd: {k.departure_time} -> Przyjazd: {k.arrival_time} | Cena: {k.price:.2f} PLN | ID: {k.route_id}")
        
    print("\n" + "=" * 50)
    print(f"KIERUNEK POWRÓT: Sanok -> Wrocław (znaleziono: {len(powrot)})")
    print("=" * 50)
    for k in powrot:
        print(f"Odjazd: {k.departure_time} -> Przyjazd: {k.arrival_time} | Cena: {k.price:.2f} PLN | ID: {k.route_id}")
    print("=" * 50)

if __name__ == "__main__":
    main()
