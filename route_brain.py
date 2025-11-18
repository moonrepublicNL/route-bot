import os
import json
import random
import re # Nodig voor JSON-parsing
from pathlib import Path
from openai import OpenAI # Importeer de klasse, maar initialiseer nog niet
import datetime # Nodig voor get_weekday

BASE = Path(__file__).parent
TRAINING_JSON = BASE / "data" / "routes_training.json"

# De client wordt NIET meer hier geïnitialiseerd om crash bij opstarten te voorkomen
# client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY")) # <-- VERWIJDERD

# -------------------------------------------------
# Utility Functies (Onveranderd)
# -------------------------------------------------
def validate_and_fix(new_request, llm_result):
    """
    new_request: originele input van de app
    llm_result: JSON dat LLM teruggeeft
    """

    required_stops = [s["address"] for s in new_request["stops"]]
    buses = new_request.get("buses", [])
    max_stops = new_request.get("max_stops_per_bus", 18)

    result = llm_result.get("bus_routes", {})

    # Als structure ontbreekt → volledige fallback
    if not isinstance(result, dict):
        return fallback(new_request)

    # Verzamel alle geplande stops
    planned = []
    for bus, arr in result.items():
        if isinstance(arr, list):
            planned.extend(arr)

    # 1. Duplicaten check
    if len(planned) != len(set(planned)):
        return fallback(new_request)

    # 2. Check op ontbrekende adressen
    if set(planned) != set(required_stops):
        return fallback(new_request)

    # 3. Max-stops per bus check
    for bus, arr in result.items():
        if len(arr) > max_stops:
            return fallback(new_request)

    # 4. Logica voor minimaal 8 stops per route
    # Maandag: altijd 1 route
    weekday = get_weekday(new_request["date"])  # 0 = maandag
    if weekday == 0:
        # maandag → alles in Ocho, Rebel leeg
        return force_single_route(new_request)

    # Niet maandag → 2 routes mogen, maar alleen als beide >= 8 stops
    if len(required_stops) < 16:
        # nooit 2 routes bij minder dan 16 stops
        return force_single_route(new_request)

    # 5. Indien 2 routes, maar 1 route < 8 stops → fallback naar 1 bus
    filled_buses = {bus: arr for bus, arr in result.items() if len(arr) > 0}
    if len(filled_buses) == 2:
        arr1 = list(filled_buses.values())[0]
        arr2 = list(filled_buses.values())[1]
        if len(arr1) < 8 or len(arr2) < 8:
            return force_single_route(new_request)

    return llm_result  # geldig


def fallback(new_request):
    """Alle stops in Ocho, Rebel leeg."""
    stops = [s["address"] for s in new_request["stops"]]
    return {
        "bus_routes": {
            "Ocho": stops,
            "Rebel": []
        }
    }


def force_single_route(new_request):
    """Hard in 1 bus zetten volgens regels."""
    stops = [s["address"] for s in new_request["stops"]]
    return {
        "bus_routes": {
            "Ocho": stops,
            "Rebel": []
        }
    }


def get_weekday(date_str):
    y, m, d = map(int, date_str.split("-"))
    return datetime.date(y, m, d).weekday()  # 0 = maandag


# -------------------------------------------------
# 1. Training-routes laden (Onveranderd)
# -------------------------------------------------
def load_training_routes(path: Path, max_routes: int = 50):
    with path.open("r", encoding="utf-8") as f:
        routes = json.load(f)
    if len(routes) > max_routes:
        routes = random.sample(routes, max_routes)
    return routes


# -------------------------------------------------
# 2. Voorbeelden uit trainingsdata bouwen (Onveranderd)
# -------------------------------------------------
def build_examples(training_routes, num_examples: int = 3):
    """
    training_routes: lijst dicts met o.a.
      - date
      - bus_name
      - address_sequence (lijst met adressen in volgorde)
    """
    examples = []
    for r in training_routes[:num_examples]:
        examples.append({
            "date": r.get("date", "onbekend"),
            "bus_name": r.get("bus_name", "onbekend"),
            "historical_stops": r.get("address_sequence", []),
        })
    return examples


# -------------------------------------------------
# 3. Prompt bouwen (Onveranderd)
# -------------------------------------------------
def build_prompt(examples, new_request):
    """
    new_request:
      {
        "date": "YYYY-MM-DD",
        "max_stops_per_bus": 18,
        "buses": ["Ocho","Rebel"],
        "stops": [{"address": "...", "colli": 3}, ...]
      }
    """
    parts = []

    instruction = (
        "Je bent een expert in het maken van bezorgroutes in Nederland.\n"
        "Je moet ALLE aangeleverde adressen verdelen over de beschikbare bussen.\n"
        "\n"
        "Algemene regels:\n"
        "1. GEEN enkel adres mag worden overgeslagen, verwijderd of verdubbeld.\n"
        "2. Elk adres komt precies één keer voor in precies één bus.\n"
        "3. Maximaal {max} stops per bus.\n"
        "4. Groepeer adressen geografisch logisch.\n"
        "\n"
        "Specifieke regels per dag en regio:\n"
        "- Maandag (Monday): altijd 1 route Amsterdam. Alle adressen (ook buiten Amsterdam) in één bus, "
        "maar houd zoveel mogelijk Amsterdam-clusters bij elkaar.\n"
        "- Dinsdag (Tuesday): altijd 2 routes, beide in/om Amsterdam. Verdeel de Amsterdam-adressen over 2 bussen, "
        "beide met maximaal {max} stops en minimaal 8 stops per bus als het totaal dat toelaat.\n"
        "- Woensdag (Wednesday): zelfde als dinsdag: 2 routes Amsterdam.\n"
        "- Donderdag (Thursday): 2 routes met duidelijke scheiding:\n"
        "    • Route 1 = Amsterdam en directe omgeving.\n"
        "    • Route 2 = Randstad: Rotterdam, Den Haag, Leiden, Schiedam en andere niet-Amsterdam-steden.\n"
        "  Amsterdam en Randstad mogen nooit door elkaar in dezelfde bus.\n"
        "- Vrijdag (Friday): 2 routes:\n"
        "    • Route 1 = Amsterdam e.o.\n"
        "    • Route 2 = Utrecht en omgeving (alle adressen in Utrecht e.d. moeten samen in één bus).\n"
        "\n"
        "Strikte scheiding:\n"
        "- Adressen buiten Amsterdam (Utrecht, Rotterdam, Den Haag, Leiden, Schiedam etc.) "
        "moeten altijd op een andere route zitten dan de pure Amsterdam-route.\n"
        "- Als er zowel Amsterdam- als Utrecht-adressen zijn op dezelfde dag: Amsterdam in één bus, Utrecht in de andere.\n"
        "- Als er Amsterdam + Randstad (Rotterdam/Den Haag/Leiden/Schiedam) zijn op donderdag: "
        "Amsterdam in één bus, Randstad in de andere.\n"
        "\n"
        "Belangrijk:\n"
        "- Gebruik zo min mogelijk bussen binnen de regels hierboven.\n"
        "- Als er meer adressen zijn dan in één bus passen (>{max} stops), moet je verplicht over 2 bussen verdelen.\n"
        "- Als er 2 bussen gebruikt worden, streef ernaar dat beide bussen minimaal 8 stops hebben, "
        "als het totaal aantal stops dat toelaat.\n"
        "- Output moet ALTIJD een geldig JSON-object zijn met alleen 'bus_routes', geen uitlegtekst.\n"
    ).format(max=new_request["max_stops_per_bus"])

    parts.append(instruction)

    parts.append("\nVOORBEELDEN UIT HET VERLEDEN:\n")
    for ex in examples:
        parts.append(
            f"- Datum: {ex['date']}, Bus: {ex['bus_name']}\n"
            f"  Route: " + " -> ".join(ex["historical_stops"])
        )

    parts.append("\nNIEUWE AANVRAAG:\n")
    parts.append(f"Datum: {new_request['date']}")
    parts.append("Bussen: " + ", ".join(new_request["buses"]))
    parts.append("Max stops per bus: " + str(new_request["max_stops_per_bus"]))

    parts.append("Adressen:")
    for s in new_request["stops"]:
        addr = s["address"]
        colli = s.get("colli")
        if colli is not None:
            parts.append(f"- {addr} (colli: {colli})")
        else:
            parts.append(f"- {addr}")

    parts.append(
        "\nAntwoord uitsluitend in dit JSON-formaat:\n"
        "{\n"
        '  "bus_routes": {\n'
        '    "Ocho": ["adres 1", "adres 2", ...],\n'
        '    "Rebel": ["adres 3", "adres 4", ...]\n'
        "  }\n"
        "}\n"
    )

    return "\n".join(parts)


# -------------------------------------------------
# 4. LLM-call (GECORRIGEERDE FUNCTIE)
# -------------------------------------------------
def call_llm(prompt: str) -> dict:
    print("=== PROMPT AAN LLM ===")
    print(prompt)
    print("=== EINDE PROMPT ===")

    # 1. API Key Check & Lazy Initialisatie
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY is niet ingesteld in de omgeving.")
        # Dit geeft een 500-error, maar de server blijft op /health werken
        raise ValueError("OpenAI API key ontbreekt. Check Railway Variables.")
    
    client = OpenAI(api_key=api_key)

    # 2. Moderne OpenAI Call
    try:
        completion = client.chat.completions.create(
            # Let op: model naam moet kloppen met wat je gebruikt (gpt-4o-mini is goed)
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            # Forceer JSON output, dit maakt regex parsen vaak overbodig
            response_format={"type": "json_object"}
        )
        raw = completion.choices[0].message.content

    except Exception as e:
        print(f"LLM API Call Error: {e}")
        # Val terug naar de harde fallback
        return {
            "bus_routes": {
                "Ocho": ["API Error Fallback"],
                "Rebel": []
            }
        }

    # 3. JSON Parising
    try:
        # Als response_format={"type": "json_object"} is gebruikt, is dit direct JSON
        return json.loads(raw)
    except Exception:
        # Als de LLM zich niet aan het JSON-formaat hield (fallback logica)
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            json_str = m.group(0)
            try:
                return json.loads(json_str)
            except Exception:
                pass # Kan het JSON-blok niet parsen

        print("Kon model-output niet parsen. Ruwe output:")
        print(raw)
        return {
            "bus_routes": {
                "Ocho": ["Parsing Error Fallback"],
                "Rebel": []
            }
        }


# -------------------------------------------------
# 5. Publieke functie voor server/app (Onveranderd)
# -------------------------------------------------
def optimize_route(new_request: dict) -> dict:
    if not TRAINING_JSON.exists():
        raise FileNotFoundError(f"Training JSON ontbreekt: {TRAINING_JSON}")

    training_routes = load_training_routes(TRAINING_JSON, max_routes=50)
    examples = build_examples(training_routes, num_examples=3)
    prompt = build_prompt(examples, new_request)
    raw = call_llm(prompt)
    clean = validate_and_fix(new_request, raw)
    return clean


# -------------------------------------------------
# 6. CLI-test (Onveranderd)
# -------------------------------------------------
def main():
    test_request = {
        "date": "2025-03-18",
        "max_stops_per_bus": 18,
        "buses": ["Ocho", "Rebel"],
        "stops": [
            {"address": "Portsmuiden 11, Amsterdam, NL", "colli": 0},
            {"address": "Bilderdijkstraat 99, Amsterdam, NL", "colli": 8},
            {"address": "Keizersgracht 516, Amsterdam, NL", "colli": 4},
            {"address": "Willemstraat 9, Utrecht, NL", "colli": 10},
        ],
    }

    result = optimize_route(test_request)
    print("=== RESULTAAT VAN ROUTE-BREIN ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()