import json
import requests

def debug_neobus():
    url = "https://neobus.pl/"
    
    # Dokładne dane formularza jak z przeglądarki
    payload = {
        "ajax": "true",
        "dataType": "json",
        "module": "neotickets",
        "step": "1",
        "ticket_type": "student",
        "initial_stop": "77",
        "final_stop": "17",
        "passengers": "1",
        "date_there": "30.11.2026",
        "date_return": "30.11.2026",
        "initial_stop_name": "WROCŁAW PKS Polbus",
        "final_stop_name": "SANOK D.A. Lipińskiego ",
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://neobus.pl/",
        "Origin": "https://neobus.pl",
    }

    print(">>> Wysyłam bezpośrednie żądanie POST...")
    response = requests.post(url, data=payload, headers=headers, timeout=20)
    
    print(f">>> Status HTTP: {response.status_code}")
    print(f">>> Nagłówki odpowiedzi: {dict(response.headers)}")
    
    try:
        data = response.json()
        print(f">>> Typ odpowiedzi: JSON")
        print(f">>> Główne klucze w JSON: {list(data.keys())}")
        
        if "ga4_data" in data:
            print(">>> SUKCES: 'ga4_data' jest w odpowiedzi!")
            print(json.dumps(data["ga4_data"], indent=2, ensure_ascii=False)[:600])
        else:
            print(">>> BRAK 'ga4_data'. Pełny zrzut JSON:")
            print(json.dumps(data, indent=2, ensure_ascii=False)[:1000])
            
    except Exception as e:
        print(f">>> Odpowiedź NIE JEST JSON-em. Błąd: {e}")
        print(">>> Początek treści odpowiedzi:")
        print(response.text[:1000])

if __name__ == "__main__":
    debug_neobus()
