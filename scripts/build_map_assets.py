#!/usr/bin/env python3

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from json import JSONDecodeError
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PROVINCE_JSON = DATA_DIR / "china-provinces.json"
CITY_JSON = DATA_DIR / "china-cities.json"
PROVINCE_JS = DATA_DIR / "china-provinces.js"
CITY_JS = DATA_DIR / "china-cities.js"
LOCATION_INDEX_JSON = DATA_DIR / "china-location-index.json"
LOCATION_INDEX_JS = DATA_DIR / "china-location-index.js"
SOUTH_INSET_PROVINCES_JSON = DATA_DIR / "china-south-inset-provinces.json"
SOUTH_INSET_PROVINCES_JS = DATA_DIR / "china-south-inset-provinces.js"
SOUTH_INSET_ISLANDS_JSON = DATA_DIR / "china-south-inset-islands.json"
SOUTH_INSET_ISLANDS_JS = DATA_DIR / "china-south-inset-islands.js"
RAW_CITY_DIR = DATA_DIR / "raw-city-boundaries"
REGION_SUFFIX_PATTERN = re.compile(
    r"(特别行政区|维吾尔自治区|壮族自治区|回族自治区|自治区|省|市|地区|盟|自治州)$"
)
SOUTH_INSET_PROVINCE_CODES = {
    "440000",
    "450000",
    "460000",
    "810000",
    "820000",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def dump_js(path: Path, variable_name: str, payload: dict[str, Any]) -> None:
    content = f"window.{variable_name} = {json.dumps(payload, ensure_ascii=False)};\n"
    path.write_text(content, encoding="utf-8")


def normalize_region_name(name: str | None) -> str:
    if not name:
        return ""

    return REGION_SUFFIX_PATTERN.sub("", name.strip())


def collect_aliases(*names: str | None) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()

    for name in names:
        for alias in (name, normalize_region_name(name)):
            if not alias or alias in seen:
                continue
            aliases.append(alias)
            seen.add(alias)

    return aliases


def infer_kind(level: int | None) -> str:
    if level == 1:
        return "province"
    if level == 2:
        return "prefecture"
    if level == 3:
        return "district"
    return "unknown"


def iterate_points(coordinates: Any) -> list[list[float]]:
    points: list[list[float]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            if len(node) >= 2 and all(isinstance(value, (int, float)) for value in node[:2]):
                points.append(node[:2])
                return

            for child in node:
                walk(child)

    walk(coordinates)
    return points


def compute_feature_bounds(feature: dict[str, Any]) -> tuple[float, float, float, float]:
    points = iterate_points(feature["geometry"]["coordinates"])
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def compute_features_bounds(
    features: list[dict[str, Any]],
) -> tuple[float, float, float, float]:
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    for feature in features:
        left, bottom, right, top = compute_feature_bounds(feature)
        min_x = min(min_x, left)
        min_y = min(min_y, bottom)
        max_x = max(max_x, right)
        max_y = max(max_y, top)

    return min_x, min_y, max_x, max_y


def compute_ring_area(ring: list[list[float]]) -> float:
    area = 0.0

    for index in range(len(ring) - 1):
        x1, y1 = ring[index]
        x2, y2 = ring[index + 1]
        area += x1 * y2 - x2 * y1

    return abs(area) / 2


def contract_bounds(
    bounds: tuple[float, float, float, float],
    x_ratio: float,
    y_ratio: float,
) -> tuple[float, float, float, float]:
    left, bottom, right, top = bounds
    width = right - left
    height = top - bottom
    dx = width * x_ratio
    dy = height * y_ratio
    return left + dx, bottom + dy, right - dx, top - dy


def transform_coordinates(
    coordinates: Any, scale: float, offset_x: float, offset_y: float
) -> Any:
    if isinstance(coordinates, list):
        if len(coordinates) >= 2 and all(isinstance(value, (int, float)) for value in coordinates[:2]):
            return [coordinates[0] * scale + offset_x, coordinates[1] * scale + offset_y]

        return [transform_coordinates(child, scale, offset_x, offset_y) for child in coordinates]

    return coordinates


def build_south_inset_geojsons(
    province_geojson: dict[str, Any], city_geojson: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_province_features = [
        feature
        for feature in province_geojson["features"]
        if feature.get("properties", {}).get("code") in SOUTH_INSET_PROVINCE_CODES
    ]
    source_island_features = [
        feature
        for feature in city_geojson["features"]
        if feature.get("properties", {}).get("code") == "460300"
    ]

    inset_feature = next(
        feature
        for feature in province_geojson["features"]
        if (feature.get("properties", {}).get("fullname") or feature.get("properties", {}).get("name"))
        == "南海诸岛及缩略图"
    )
    dashed_line_feature = next(
        feature
        for feature in province_geojson["features"]
        if (feature.get("properties", {}).get("fullname") or feature.get("properties", {}).get("name"))
        == "中国南海十段线"
    )

    inset_polygons = inset_feature["geometry"]["coordinates"]
    polygon_summaries: list[dict[str, Any]] = []

    for index, polygon in enumerate(inset_polygons):
        ring = polygon[0]
        polygon_summaries.append(
            {
                "index": index,
                "area": compute_ring_area(ring),
                "bounds": compute_feature_bounds(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": [ring]},
                    }
                ),
                "polygon": polygon,
            }
        )

    frame_summary = max(
        polygon_summaries,
        key=lambda summary: (summary["bounds"][2] - summary["bounds"][0])
        * (summary["bounds"][3] - summary["bounds"][1]),
    )
    mainland_target_polygons = [
        summary
        for summary in polygon_summaries
        if summary["index"] != frame_summary["index"]
        and (summary["area"] > 0.01 or summary["bounds"][3] > 22.8)
    ]
    island_target_polygons = [
        summary
        for summary in polygon_summaries
        if summary["index"] != frame_summary["index"] and summary not in mainland_target_polygons
    ]

    mainland_target_bounds = compute_features_bounds(
        [
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [summary["polygon"]]}}
            for summary in mainland_target_polygons
        ]
    )
    island_target_bounds = contract_bounds(
        compute_features_bounds(
            [
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [summary["polygon"]]},
                }
                for summary in island_target_polygons
            ]
        ),
        0.03,
        0.04,
    )

    def clone_transformed(
        feature: dict[str, Any],
        scale: float,
        offset_x: float,
        offset_y: float,
    ) -> dict[str, Any]:
        cloned = json.loads(json.dumps(feature, ensure_ascii=False))
        cloned["geometry"]["coordinates"] = transform_coordinates(
            cloned["geometry"]["coordinates"],
            scale,
            offset_x,
            offset_y,
        )
        return cloned

    def transform_feature_group(
        features: list[dict[str, Any]],
        target_bounds: tuple[float, float, float, float],
    ) -> list[dict[str, Any]]:
        source_bounds = compute_features_bounds(features)
        source_width = source_bounds[2] - source_bounds[0]
        source_height = source_bounds[3] - source_bounds[1]
        target_width = target_bounds[2] - target_bounds[0]
        target_height = target_bounds[3] - target_bounds[1]
        scale = min(target_width / source_width, target_height / source_height)
        offset_x = (
            target_bounds[0]
            - source_bounds[0] * scale
            + (target_width - source_width * scale) / 2
        )
        offset_y = (
            target_bounds[1]
            - source_bounds[1] * scale
            + (target_height - source_height * scale) / 2
        )
        return [
            clone_transformed(feature, scale, offset_x, offset_y) for feature in features
        ]

    inset_province_features = transform_feature_group(
        source_province_features,
        mainland_target_bounds,
    )
    inset_island_features = transform_feature_group(
        source_island_features,
        island_target_bounds,
    )

    frame_left, frame_bottom, frame_right, frame_top = frame_summary["bounds"]
    frame_feature = {
        "type": "Feature",
        "properties": {
            "name": "南海缩略图边框",
            "fullname": "南海缩略图边框",
            "code": "south-sea-frame",
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [frame_left, frame_bottom],
                [frame_right, frame_bottom],
                [frame_right, frame_top],
                [frame_left, frame_top],
                [frame_left, frame_bottom],
            ]],
        },
    }

    inset_provinces = {
        "type": "FeatureCollection",
        "features": [
            *inset_province_features,
            json.loads(json.dumps(dashed_line_feature, ensure_ascii=False)),
            frame_feature,
        ],
    }
    inset_islands = {
        "type": "FeatureCollection",
        "features": inset_island_features,
    }

    return inset_provinces, inset_islands


def build_city_geojson() -> dict[str, Any]:
    provinces = load_json(PROVINCE_JSON)
    features: list[dict[str, Any]] = []
    valid_source_count = 0
    expected_source_count = sum(
        1 for province in provinces["features"] if province.get("properties", {}).get("code")
    )

    for province in provinces["features"]:
        props = province.get("properties", {})
        province_code = props.get("code")

        if not province_code:
            continue

        raw_path = RAW_CITY_DIR / f"{province_code}.json"

        if not raw_path.exists() or raw_path.stat().st_size == 0:
            continue

        try:
            city_geojson = load_json(raw_path)
        except JSONDecodeError:
            continue

        province_name = props.get("fullname") or props.get("name")
        valid_source_count += 1

        for city_feature in city_geojson.get("features", []):
            city_props = city_feature.setdefault("properties", {})
            city_props["provinceCode"] = province_code
            city_props["provinceName"] = province_name
            features.append(city_feature)

    if CITY_JSON.exists():
        current_city_geojson = load_json(CITY_JSON)
        current_feature_count = len(current_city_geojson.get("features", []))
        built_feature_count = len(features)

        if valid_source_count == 0 or (
            valid_source_count < expected_source_count and current_feature_count > built_feature_count
        ):
            return current_city_geojson

    return {"type": "FeatureCollection", "features": features}


def build_location_index(
    province_geojson: dict[str, Any], city_geojson: dict[str, Any]
) -> dict[str, Any]:
    locations: list[dict[str, Any]] = []
    by_code: dict[str, dict[str, Any]] = {}
    by_name: dict[str, list[str]] = {}

    def register(entry: dict[str, Any]) -> None:
        code = entry["code"]
        by_code[code] = entry
        locations.append(entry)

        for alias in entry["aliases"]:
            by_name.setdefault(alias, []).append(code)

    for feature in province_geojson["features"]:
        props = feature.get("properties", {})
        code = props.get("code")
        center = props.get("center")

        if not code or not isinstance(center, list) or len(center) < 2:
            continue

        fullname = props.get("fullname") or props.get("name")
        entry = {
            "code": code,
            "name": props.get("name"),
            "fullname": fullname,
            "level": props.get("level"),
            "kind": infer_kind(props.get("level")),
            "center": center,
            "provinceCode": code,
            "provinceName": fullname,
            "aliases": collect_aliases(props.get("name"), fullname),
        }
        register(entry)

    for feature in city_geojson["features"]:
        props = feature.get("properties", {})
        code = props.get("code")
        center = props.get("center")

        if not code or not isinstance(center, list) or len(center) < 2:
            continue

        fullname = props.get("fullname") or props.get("name")
        entry = {
            "code": code,
            "name": props.get("name"),
            "fullname": fullname,
            "level": props.get("level"),
            "kind": infer_kind(props.get("level")),
            "center": center,
            "provinceCode": props.get("provinceCode"),
            "provinceName": props.get("provinceName"),
            "aliases": collect_aliases(props.get("name"), fullname),
        }
        register(entry)

    for alias, codes in by_name.items():
        by_name[alias] = sorted(set(codes))

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "provinceCount": sum(1 for item in locations if item["level"] == 1),
            "prefectureCount": sum(1 for item in locations if item["level"] == 2),
            "districtCount": sum(1 for item in locations if item["level"] == 3),
            "aliasCount": len(by_name),
        },
        "locations": locations,
        "byCode": by_code,
        "byName": by_name,
    }


def main() -> None:
    province_geojson = load_json(PROVINCE_JSON)
    city_geojson = build_city_geojson()
    location_index = build_location_index(province_geojson, city_geojson)
    south_inset_provinces, south_inset_islands = build_south_inset_geojsons(
        province_geojson, city_geojson
    )

    dump_json(CITY_JSON, city_geojson)
    dump_json(LOCATION_INDEX_JSON, location_index)
    dump_json(SOUTH_INSET_PROVINCES_JSON, south_inset_provinces)
    dump_json(SOUTH_INSET_ISLANDS_JSON, south_inset_islands)
    dump_js(PROVINCE_JS, "CHINA_PROVINCES_GEOJSON", province_geojson)
    dump_js(CITY_JS, "CHINA_CITIES_GEOJSON", city_geojson)
    dump_js(LOCATION_INDEX_JS, "CHINA_LOCATION_INDEX", location_index)
    dump_js(SOUTH_INSET_PROVINCES_JS, "CHINA_SOUTH_INSET_PROVINCES_GEOJSON", south_inset_provinces)
    dump_js(SOUTH_INSET_ISLANDS_JS, "CHINA_SOUTH_INSET_ISLANDS_GEOJSON", south_inset_islands)

    print(f"Built {CITY_JSON.relative_to(ROOT)} with {len(city_geojson['features'])} features")
    print(
        f"Built {LOCATION_INDEX_JSON.relative_to(ROOT)} with "
        f"{location_index['stats']['aliasCount']} aliases"
    )
    print(
        f"Built {SOUTH_INSET_PROVINCES_JSON.relative_to(ROOT)} with "
        f"{len(south_inset_provinces['features'])} features"
    )
    print(
        f"Built {SOUTH_INSET_ISLANDS_JSON.relative_to(ROOT)} with "
        f"{len(south_inset_islands['features'])} features"
    )
    print(f"Built {PROVINCE_JS.relative_to(ROOT)}")
    print(f"Built {CITY_JS.relative_to(ROOT)}")
    print(f"Built {LOCATION_INDEX_JS.relative_to(ROOT)}")
    print(f"Built {SOUTH_INSET_PROVINCES_JS.relative_to(ROOT)}")
    print(f"Built {SOUTH_INSET_ISLANDS_JS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
