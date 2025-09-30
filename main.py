# main.py (with updated /calculate_score)

import os
import requests
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2
import secrets
from fastapi.responses import HTMLResponse

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

tourist_state = {}

class LocationData(BaseModel):
    latitude: float
    longitude: float
    # ✅ OPTIONAL: Add destination coordinates
    destination_lat: float | None = None
    destination_lon: float | None = None


class TrackingData(BaseModel):
    tourist_id: str
    latitude: float
    longitude: float
    destination_lat: float | None = None
    destination_lon: float | None = None

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = map(radians, [lat1, lon1, lat2, lon2])
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    a = sin(dlat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

def get_weather_data(latitude: float, longitude: float) -> dict | None:
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key:
        print("⚠️ OpenWeather API key not found. Skipping weather check.")
        return None
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={latitude}&lon={longitude}&appid={api_key}&units=metric"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error calling Weather API: {e}")
        return None

# --- ✅ UPDATED Safety Score Endpoint ---
@app.post("/calculate_score")
async def calculate_safety_score(location_data: LocationData):
    """
    Calculates the safety score.
    - If destination_lat and destination_lon are provided, it calculates the score for that destination.
    - Otherwise, it calculates the score for the user's current latitude and longitude.
    """
    
    # Determine which coordinates to use
    lat_to_check = location_data.destination_lat if location_data.destination_lat is not None else location_data.latitude
    lon_to_check = location_data.destination_lon if location_data.destination_lon is not None else location_data.longitude

    safety_score = 100
    reasons = []
    
    # Get weather for the relevant location
    weather = get_weather_data(lat_to_check, lon_to_check)
    
    if weather:
        main_weather = weather.get("weather", [{}])[0].get("main")
        temp = weather.get("main", {}).get("temp")
        district = weather.get("name", "Unknown Area") # Extract district/city name
        
        if main_weather in ["Rain", "Thunderstorm", "Fog", "Mist", "Snow", "Drizzle"]:
            safety_score -= 25
            reasons.append(f"Adverse weather predicted: {main_weather}.")
        if temp and temp > 35:
            safety_score -= 15
            reasons.append(f"Potential for extreme heat: {temp}°C.")

    # Time-based risk is always based on the current time
    current_hour = datetime.now().hour
    if current_hour < 6 or current_hour > 22:
        safety_score -= 30
        reasons.append("Late night travel increases risk.")

    safety_score = max(0, int(safety_score))
    
    return {
        "score": safety_score,
        "level": "Safe" if safety_score > 65 else "Caution" if safety_score > 35 else "Unsafe",
        "reasons": reasons,
        "district": district if weather else "N/A"
    }


# --- (Your /track and /get_nearby_attractions endpoints remain the same) ---
@app.post("/track")
async def track_location_and_detect_anomalies(data: TrackingData, background_tasks: BackgroundTasks):
    tourist_id = data.tourist_id
    now = datetime.now()
    anomalies_found = []

    if tourist_id in tourist_state:
        last_update = tourist_state[tourist_id]
        
        # Prolonged Inactivity
        time_diff_inactive = now - last_update["timestamp"]
        distance_moved = haversine(data.latitude, data.longitude, last_update["lat"], last_update["lon"])
        
        if time_diff_inactive > timedelta(minutes=20) and distance_moved < 0.05:
            anomaly = f"Prolonged inactivity detected for tourist {tourist_id}."
            print(f"🚨 ANOMALY: {anomaly}")
            anomalies_found.append(anomaly)
            
        # Deviation from Planned Route
        if data.destination_lat and last_update.get("destination"):
            current_dist_to_dest = haversine(data.latitude, data.longitude, data.destination_lat, data.destination_lon)
            prev_dist_to_dest = haversine(last_update["lat"], last_update["lon"], data.destination_lat, data.destination_lon)
            
            if current_dist_to_dest > prev_dist_to_dest + 0.2:
                anomaly = f"Route deviation detected for tourist {tourist_id}."
                print(f"🚨 ANOMALY: {anomaly}")
                anomalies_found.append(anomaly)

    tourist_state[tourist_id] = {
        "lat": data.latitude,
        "lon": data.longitude,
        "timestamp": now,
        "destination": {"lat": data.destination_lat, "lon": data.destination_lon} if data.destination_lat else None
    }
    
    background_tasks.add_task(check_for_sudden_dropoffs)
    
    return {"status": "location updated", "anomalies": anomalies_found}

def check_for_sudden_dropoffs():
    now = datetime.now()
    stale_threshold = timedelta(minutes=15)
    
    for tourist_id in list(tourist_state.keys()):
        if now - tourist_state[tourist_id]["timestamp"] > stale_threshold:
            anomaly = f"Sudden location drop-off for tourist {tourist_id}."
            print(f"🚨 ANOMALY: {anomaly}")
            del tourist_state[tourist_id]

@app.post("/get_nearby_attractions")
async def get_nearby_attractions(location_data: LocationData):
    api_key = os.getenv("NEXT_PUBLIC_TOMTOM_KEY")
    if not api_key:
        print("❌ Error: TomTom API key not found.")
        return {"error": "Server configuration issue."}

    search_keywords = ["park", "museum", "beach", "temple", "zoo", "garden", "historical site", "aquarium", "monument", "art gallery"]
    attractions = []
    seen_names = set()

    for keyword in search_keywords:
        url = (
            f"https://api.tomtom.com/search/2/search/{keyword}.json"
            f"?key={api_key}"
            f"&lat={location_data.latitude}"
            f"&lon={location_data.longitude}"
            f"&radius=10000"
            f"&limit=5"
        )
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            if data.get("results"):
                for result in data["results"]:
                    poi_name = result.get("poi", {}).get("name")
                    if poi_name and poi_name not in seen_names:
                        attractions.append({
                            "name": poi_name,
                            "address": result.get("address", {}).get("freeformAddress"),
                            "distance": result.get("dist"),
                            "lat": result.get("position", {}).get("lat"),
                            "lon": result.get("position", {}).get("lon"),
                        })
                        seen_names.add(poi_name)
        except requests.exceptions.RequestException as e:
            print(f"Error searching for keyword '{keyword}': {e}")
            continue

    attractions.sort(key=lambda x: x["distance"])
    return attractions[:30]