from flask import Flask, request, jsonify, render_template
from config import Config
import re, ast, subprocess, requests, urllib.parse

app = Flask(__name__)
app.config.from_object(Config)

GOOGLE_MAPS_API_KEY = app.config['GOOGLE_MAPS_API_KEY']


def is_safe_query(query: str) -> bool:
    return bool(re.match(r'^[\w\s,.-]+$', query))

def query_llm(prompt: str) -> str:
    try:
        result = subprocess.run(
            ['ollama', 'run', 'llama3.2:latest', prompt],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error running Ollama: {e.stderr}"

import json


def extract_places_from_llm(llm_output: str):
    try:
        # Coba parse langsung sebagai list
        try:
            parsed = json.loads(llm_output)
            if isinstance(parsed, list):
                all_places = []
                for item in parsed:
                    if isinstance(item, str):
                        try:
                            # Coba json.loads dulu
                            item_data = json.loads(item)
                        except json.JSONDecodeError:
                            # Jika gagal, coba ast.literal_eval (lebih toleran)
                            try:
                                item_data = ast.literal_eval(item)
                            except Exception as e:
                                print(f"Skipping invalid string item (literal_eval failed): {e}")
                                continue
                        if isinstance(item_data, dict) and 'name' in item_data:
                            all_places.append({
                                'name': item_data['name'],
                                'address': item_data.get('address', item_data['name'])
                            })
                    elif isinstance(item, dict) and 'name' in item:
                        all_places.append({
                            'name': item['name'],
                            'address': item.get('address', item['name'])
                        })
                return all_places

        except json.JSONDecodeError:
            # Jika gagal, cari blok JSON array dalam teks
            json_blocks = re.findall(r'\[\s*\{.*?\}\s*\]', llm_output, re.DOTALL)

            all_places = []
            for block in json_blocks:
                try:
                    data = json.loads(block)
                    for item in data:
                        if isinstance(item, dict) and 'name' in item:
                            all_places.append({
                                'name': item['name'],
                                'address': item.get('address', item['name'])
                            })
                except json.JSONDecodeError as e:
                    print("Skipping invalid block:", e)
                    continue

            return all_places

    except Exception as e:
        print("Error parsing LLM output:", e)
        return []

def geocode_address(address):
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {'address': address, 'key': GOOGLE_MAPS_API_KEY}
    res = requests.get(url, params=params).json()
    print('res', res)
    if res['status'] == 'OK':
        loc = res['results'][0]['geometry']['location']
        return loc['lat'], loc['lng']
    return None, None

def getPlace(place):
    if not place or not is_safe_query(place):
        return jsonify({'error': 'Invalid or missing place parameter'}), 400

    api_key = app.config['GOOGLE_MAPS_API_KEY']
    query = place

    # Google Places Text Search API URL
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        'query': query,
        'key': api_key,
    }

    response = requests.get(url, params=params)
    if response.status_code != 200:
        return jsonify({'error': 'Failed to fetch data from Google Places API'}), 500

    data = response.json()
    print('data', data)
    # kamu bisa pilih kembalikan 'results' saja atau proses sesuai kebutuhan
    places = []
    for place in data.get('results', []):
        places.append({
            'name': place.get('name'),
            'address': place.get('formatted_address'),
            'lat': place.get('geometry', {}).get('location', {}).get('lat'),
            'lng': place.get('geometry', {}).get('location', {}).get('lng'),
            'rating': place.get('rating'),
            'place_id': place.get('place_id'),
        })

    return places

@app.route('/search-place', methods=['GET'])
def search_place():
    query = request.args.get("query")
    if not query or not is_safe_query(query):
        return jsonify({'error': 'Invalid or missing query parameter'}), 400

    prompt = (
        f"{query}, show all the data address"
        f"in JSON format, with no other statement the results must like this:"
        f'[{{"name": "Place Name", "address": "The Address"}}]'
    )
    llm_answer = query_llm(prompt)

    print('llm_answer', llm_answer)
    places = extract_places_from_llm(llm_answer)
    print('places', places)

    markers = []
    marker_urls = []
    reportAPIGoogle = None
    for loc in places:
        lat, lng = geocode_address(loc['address'])
        if lat and lng:
            marker_urls.append({'name': loc.get('name'), 'address': loc.get('address'), 'lat': lat, 'lng': lng})
        else:
            reportAPIGoogle = 'Limit Quotas Google Api'

    dataResPlace = []
    if len(marker_urls) == 0:
        for loc in places:
            resPlace = getPlace(loc['address'])
            dataResPlace.append(resPlace)

        print('dataResPlace', dataResPlace)
        if len(dataResPlace) > 0:
            marker_urls = [item for sublist in dataResPlace for item in sublist]

    print('marker_urls',marker_urls)

    return jsonify({
        "llm_answer": llm_answer,
        "places_found": marker_urls,
        'reportAPIGoogle': None if len(marker_urls) > 0 else reportAPIGoogle
    })


resPlaces = []

@app.route('/')
def index():

    return render_template('map.html', resPlaces=resPlaces, api_key=GOOGLE_MAPS_API_KEY)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=app.config['PORT'], debug=True)


