#!/usr/bin/env python3
"""Маршрут словами и картинкой — для контакта «Claude» на мосту.

    tools/route.py "откуда" "куда" [--mode foot|bike|car] [--out файл.png] [--near Москва]
                   [--parts N --parts-dir каталог]

Печатает пошаговое описание по-русски («Поверните направо на Кремлёвский
проезд, 180 м»), а в файл кладёт карту с линией маршрута. С --parts маршрут
режется на N кусков по длине: для каждого — своя карта крупнее
(part-1.png, part-2.png, … в --parts-dir) и свои шаги, чтобы отдавать их
на телефон по одному. «Куда» может
быть «метро» (или «ближайшее метро», «станция») — тогда ищется ближайшая
станция метро. Всё на открытых сервисах без ключей: геокодер и Overpass
OpenStreetMap, маршрут — OSRM (routing.openstreetmap.de), картинка —
статические Яндекс.Карты. Они бесплатные и небыстрые: запрос занимает
несколько секунд, и злоупотреблять ими не стоит.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request

UA = "icq-tg-bridge route helper (https://github.com/Tamahome-M/icq-tg-bridge)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"
OSRM = "https://routing.openstreetmap.de/routed-{profile}/route/v1/{profile}/"
STATIC_MAP = "https://static-maps.yandex.ru/1.x/"
METRO = re.compile(r"^(ближайш\w*\s+)?(метро|станци\w*(\s+метро)?)$", re.I)

TURNS = {
    "left": "налево", "right": "направо", "sharp left": "резко налево",
    "sharp right": "резко направо", "slight left": "левее", "slight right": "правее",
    "straight": "прямо", "uturn": "разворот",
}


def fetch(url: str, data: bytes | None = None) -> dict | list:
    request = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=40) as response:
        return json.load(response)


def geocode(place: str, near: str) -> tuple[float, float, str]:
    query = place if not near or near.lower() in place.lower() else f"{place}, {near}"
    found = fetch(NOMINATIM + "?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "limit": 1, "accept-language": "ru"}))
    if not found:
        raise SystemExit(f"не нашёл место: {place}")
    hit = found[0]
    parts = [p.strip() for p in hit["display_name"].split(",")]
    # У адреса первым идёт номер дома — тогда берём и улицу.
    name = ", ".join(parts[:2]) if parts and parts[0].replace("/", "").isdigit() else parts[0]
    return float(hit["lat"]), float(hit["lon"]), name


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Метры по прямой."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def nearest_metro(lat: float, lon: float) -> tuple[float, float, str]:
    query = f"[out:json][timeout:25];node(around:3000,{lat},{lon})[station=subway];out body;"
    answer = fetch(OVERPASS, data=urllib.parse.urlencode({"data": query}).encode())
    stations = [(distance((lat, lon), (e["lat"], e["lon"])), e) for e in answer.get("elements", [])
                if e.get("tags", {}).get("name")]
    if not stations:
        raise SystemExit("метро в трёх километрах не нашлось")
    _, best = min(stations, key=lambda pair: pair[0])
    return best["lat"], best["lon"], "метро " + best["tags"]["name"]


def decode_polyline(text: str) -> list[tuple[float, float]]:
    points, index, lat, lon = [], 0, 0, 0
    while index < len(text):
        for coord in ("lat", "lon"):
            shift = result = 0
            while True:
                byte = ord(text[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if coord == "lat":
                lat += delta
            else:
                lon += delta
        points.append((lat / 1e5, lon / 1e5))
    return points


def describe(step: dict, mode: str) -> str:
    kind = step["maneuver"]["type"]
    modifier = step["maneuver"].get("modifier", "")
    name = step.get("name") or ""
    where = f" на {name}" if name else ""
    along = f" по {name}" if name else ""
    if kind == "depart":
        return ("Идите" if mode == "foot" else "Поезжайте") + along
    if kind == "arrive":
        return "Вы на месте" + (f" ({TURNS.get(modifier, modifier)})" if modifier in ("left", "right") else "")
    if kind in ("turn", "end of road", "fork", "merge", "on ramp", "off ramp", "exit rotary", "exit roundabout"):
        turn = TURNS.get(modifier, modifier)
        if turn in ("прямо", ""):
            return f"Прямо{along}"
        if turn in ("левее", "правее"):
            return f"Держитесь {turn}{where}"
        return f"Поверните {turn}{where}"
    if kind in ("roundabout", "rotary"):
        exit_no = step["maneuver"].get("exit")
        return f"На кольце — {exit_no}-й съезд{where}" if exit_no else f"По кольцу{where}"
    if kind in ("new name", "continue", "notification", "use lane"):
        return f"Далее{along}"
    return f"{kind}{where}"


def meters(value: float) -> str:
    return f"{round(value / 100) / 10:g} км" if value >= 1000 else f"{int(round(value / 10) * 10)} м"


def thin_line(points: list[tuple[float, float]], limit: int = 80) -> str:
    # Линию прореживаем: адрес картинки не должен расти без меры.
    step = max(1, len(points) // limit)
    thin = points[::step] + ([points[-1]] if (len(points) - 1) % step else [])
    return ",".join(f"{lon:.5f},{lat:.5f}" for lat, lon in thin)


def static_map(points: list[tuple[float, float]], out: str,
               segment: list[tuple[float, float]] | None = None,
               labels: tuple[str, str] = ("am", "bm")) -> None:
    """Карта с линией маршрута; segment — выделенный кусок, под который и
    выбирается масштаб (остальной маршрут остаётся тонкой серой линией)."""
    focus = segment or points
    params = {"l": "map", "size": "450,450"}
    if segment:
        lats = [lat for lat, _ in segment]
        lons = [lon for _, lon in segment]
        span_lat = max(lats) - min(lats)
        span_lon = max(lons) - min(lons)
        pad = max(span_lat, span_lon * math.cos(math.radians(lats[0])), 0.0015) * 0.35
        params["ll"] = f"{(min(lons) + max(lons)) / 2:.5f},{(min(lats) + max(lats)) / 2:.5f}"
        params["spn"] = f"{max(span_lon, 0.002) + pad * 2:.5f},{max(span_lat, 0.0015) + pad * 2:.5f}"
    # Метки: А и Б у концов маршрута, зелёная/красная — у концов куска.
    params["pt"] = (f"{focus[0][1]:.5f},{focus[0][0]:.5f},pm2{labels[0]}~"
                    f"{focus[-1][1]:.5f},{focus[-1][0]:.5f},pm2{labels[1]}")
    # Адрес картинки не длиннее ~2 КБ, иначе сервер отвечает 400: линию
    # прореживаем, пока не уложимся; кусок рисуется подробнее всего маршрута.
    for limit in (80, 60, 45, 30, 20, 12):
        if segment:
            lines = [f"c:9e9e9eff,w:3,{thin_line(points, max(10, limit * 2 // 3))}",
                     f"c:1e64ffff,w:6,{thin_line(segment, limit)}"]
        else:
            lines = [f"c:1e64ffff,w:5,{thin_line(points, limit)}"]
        params["pl"] = "~".join(lines)
        url = STATIC_MAP + "?" + urllib.parse.urlencode(params)
        if len(url) <= 2000:
            break
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=40) as response, open(out, "wb") as target:
        target.write(response.read())


def split_route(points: list[tuple[float, float]], parts: int) -> list[list[tuple[float, float]]]:
    """Режет линию маршрута на куски примерно равной длины."""
    total = sum(distance(points[i], points[i + 1]) for i in range(len(points) - 1))
    if parts < 2 or total <= 0:
        return [points]
    target = total / parts
    pieces, current, walked = [], [points[0]], 0.0
    for i in range(len(points) - 1):
        walked += distance(points[i], points[i + 1])
        current.append(points[i + 1])
        if walked >= target * (len(pieces) + 1) and len(pieces) < parts - 1:
            pieces.append(current)
            current = [points[i + 1]]
    if len(current) > 1 or not pieces:
        pieces.append(current)
    return pieces


def main() -> int:
    parser = argparse.ArgumentParser(description="маршрут словами и картинкой")
    parser.add_argument("origin")
    parser.add_argument("destination")
    parser.add_argument("--mode", choices=("foot", "bike", "car"), default="foot")
    parser.add_argument("--out", default="", help="куда положить карту (PNG)")
    parser.add_argument("--near", default="Москва", help="город, если в адресе его нет")
    parser.add_argument("--parts", type=int, default=0, help="порезать маршрут на столько частей")
    parser.add_argument("--parts-dir", default="", help="куда класть карты частей (part-N.png)")
    args = parser.parse_args()

    a_lat, a_lon, a_name = geocode(args.origin, args.near)
    if METRO.match(args.destination.strip()):
        b_lat, b_lon, b_name = nearest_metro(a_lat, a_lon)
    else:
        b_lat, b_lon, b_name = geocode(args.destination, args.near)

    url = (OSRM.format(profile=args.mode) + f"{a_lon},{a_lat};{b_lon},{b_lat}"
           + "?steps=true&overview=full&geometries=polyline")
    route = fetch(url)
    if route.get("code") != "Ok" or not route.get("routes"):
        raise SystemExit("маршрут не построился")
    best = route["routes"][0]
    how = {"foot": "пешком", "bike": "на велосипеде", "car": "на машине"}[args.mode]
    print(f"{a_name} → {b_name}: {meters(best['distance'])}, около {max(1, round(best['duration'] / 60))} мин {how}")
    steps = best["legs"][0]["steps"]
    points = decode_polyline(best["geometry"])
    pieces = split_route(points, args.parts) if args.parts else [points]
    # Шаг относится к той части, где он начинается.
    bounds: list[float] = []
    walked = 0.0
    for piece in pieces:
        walked += sum(distance(piece[i], piece[i + 1]) for i in range(len(piece) - 1))
        bounds.append(walked)
    at, part = 0.0, 0
    for step in steps:
        while part < len(bounds) - 1 and at >= bounds[part] - 1:
            part += 1
        step["_part"] = part
        at += step["distance"]
    for index, piece in enumerate(pieces, start=1):
        if len(pieces) > 1:
            length = sum(distance(piece[i], piece[i + 1]) for i in range(len(piece) - 1))
            print(f"Часть {index}/{len(pieces)}, {meters(length)}:")
        for step in steps:
            if step["_part"] != index - 1:
                continue
            text = describe(step, args.mode)
            if step["maneuver"]["type"] == "arrive":
                print(f"- {text}")
            elif step["distance"] >= 5:
                print(f"- {text}, {meters(step['distance'])}")
        if len(pieces) > 1 and args.parts_dir:
            os.makedirs(args.parts_dir, exist_ok=True)
            out = os.path.join(args.parts_dir, f"part-{index}.png")
            static_map(points, out, piece, labels=("am" if index == 1 else "gnm",
                                                   "bm" if index == len(pieces) else "rdm"))
            print(f"карта части: {out}")
    if args.out:
        static_map(points, args.out)
        print(f"карта: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
