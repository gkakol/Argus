import json
import requests

def test_session():
    session = requests.Session()
    
    # 1. Dokładne nagłówki przeglądarkowe
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    # Testujemy który adres jest kanoniczny (czy https://neobus.pl/ czy https://www.neobus.pl/)import json
import requests

def test_variants():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    print(">>> 1. Pobieranie ciasteczek sesyjnych...")
    res_get = session.get("https://neobus.pl/", timeout=15)
    print(f"GET Status: {res_get.status_code}")
    print("Ciasteczka:", session.cookies.get_dict())

    # Sprawdźmy, czy w HTML jest ukryty token CSRF lub czy w ciasteczkach jest csrf_cookie_name
    csrf_token = session.cookies.get("csrf_cookie_name") or session.cookies.get("csrf_test_name")
    print(f"CSRF token w cookies: {csrf_token}")

    base_payload = {
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
    if csrf_token:
        base_payload["csrf_test_name"] = csrf_token

    # 4 warianty endpointu i nagłówków
    variants = [
        # Wariant A: Standardowy POST na / bez nagłówków X-Requested-With (często triggeruje WAF)
        {
            "name": "Wariant A: URL https://neobus.pl/ (minimalne nagłówki)",
            "url": "https://neobus.pl/",
            "headers": {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://neobus.pl/",
                "Origin": "https://neobus.pl",
            }
        },
        # Wariant B: POST na /index.php (bezpośrednio do routera CodeIgnitera)
        {
            "name": "Wariant B: URL https://neobus.pl/index.php",
            "url": "https://neobus.pl/index.php",
            "headers": {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://neobus.pl/",
                "Origin": "https://neobus.pl",
            }
        },
        # Wariant C: Z exact Ajax headers i Accept application/json
        {
            "name": "Wariant C: Dokładne nagłówki AJAX z przeglądarki",
            "url": "https://neobus.pl/",
            "headers": {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "Referer": "https://neobus.pl/",
            }
        },
        # Wariant D: Bez nagłówka Origin (niektóre WAF odrzucają Origin przy POST)
        {
            "name": "Wariant D: Bez nagłówka Origin",
            "url": "https://neobus.pl/",
            "headers": {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://neobus.pl/",
            }
        }
    ]

    print("\n>>> 2. Testowanie wariantów POST...")
    for v in variants:
        try:
            r = session.post(v["url"], data=base_payload, headers=v["headers"], timeout=15)
            print(f"[{v['name']}] -> Status: {r.status_code}")
            if r.status_code == 200:
                try:
                    data = r.json()
                    print(f"   -> SUKCES! Klucze w JSON: {list(data.keys())}")
                    if "ga4_data" in data:
                        print(f"   -> ZNALEZIONO ga4_data! Kursów TAM: {len(data['ga4_data'][0].get('items', []))}")
                    return
                except Exception:
                    print(f"   -> 200 OK, ale odpowiedź to tekst: {r.text[:100]}...")
            elif r.status_code == 403:
                # Wypiszmy czy odpowiedź to błąd Apache nazwa.pl czy coś innego
                is_nazwa = "nazwa.pl" in str(r.headers)
                print(f"   -> 403 Forbidden (WAF nazwa.pl: {is_nazwa})")
        except Exception as e:
            print(f"[{v['name']}] -> Błąd: {e}")

if __name__ == "__main__":
    test_variants()
    print(">>> 1. Wykonuję GET na stronę główną, aby złapać ciasteczka sesyjne z nazwa.pl...")
    
    # max_redirects chroni przed pętlą
    session.max_redirects = 5
    
    try:
        # Próbujemy wejść na stronę główną
        r_get = session.get("https://neobus.pl/", timeout=15)
        print(f">>> GET Status: {r_get.status_code} | Ostateczny URL: {r_get.url}")
        print(f">>> Pobrane ciasteczka: {session.cookies.get_dict()}")
        target_url = r_get.url  # Użyjemy adresu, na który ostatecznie skierował serwer
    except Exception as e:
        print(f">>> Błąd GET: {e}")
        target_url = "https://neobus.pl/"

    # 2. Teraz wysyłamy POST z tymi samymi ciasteczkami sesyjnymi
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

    post_headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": target_url.rstrip("/"),
        "Referer": target_url,
    }

    print(f"\n>>> 2. Wysyłam POST na: {target_url} z ciasteczkami...")
    try:
        r_post = session.post(target_url, data=payload, headers=post_headers, timeout=20)
        print(f">>> POST Status: {r_post.status_code}")
        
        try:
            res_json = r_post.json()
            print(">>> SUKCES! Otrzymano JSON:")
            print(f">>> Klucze: {list(res_json.keys())}")
            if "ga4_data" in res_json:
                print(">>> ga4_data znalezione! Liczba relacji:", len(res_json["ga4_data"]))
                for rel in res_json["ga4_data"]:
                    print("   -", rel.get("item_list_name"), f"(kursów: {len(rel.get('items', []))})")
        except Exception:
            print(">>> Odpowiedź POST to nie JSON. Treść:")
            print(r_post.text[:400])

    except Exception as e:
        print(f">>> Błąd POST: {e}")

if __name__ == "__main__":
    test_session()
