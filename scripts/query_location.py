#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "data" / "china-location-index.json"
REGION_SUFFIX_PATTERN = re.compile(
    r"(特别行政区|维吾尔自治区|壮族自治区|回族自治区|自治区|省|市|地区|盟|自治州)$"
)
LEVEL_LABELS = {
    1: "省级/直辖市",
    2: "地级市/自治州",
    3: "区县/市辖区",
}


def normalize_region_name(name: str) -> str:
    return REGION_SUFFIX_PATTERN.sub("", name.strip())


def load_index() -> dict:
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def print_entry(entry: dict) -> None:
    level = LEVEL_LABELS.get(entry.get("level"), f"level={entry.get('level')}")
    center = entry.get("center", ["?", "?"])
    print(
        f"{entry['fullname']} | code={entry['code']} | {level} | "
        f"province={entry.get('provinceName')} | center={center[0]}, {center[1]}"
    )


def exact_match(index: dict, query: str) -> list[dict]:
    codes = index["byName"].get(query, [])
    if not codes:
        codes = index["byName"].get(normalize_region_name(query), [])
    return [index["byCode"][code] for code in codes]


def fuzzy_match(index: dict, query: str) -> list[dict]:
    seen: set[str] = set()
    matches: list[dict] = []

    for entry in index["locations"]:
        haystacks = [entry["name"], entry["fullname"], *entry["aliases"]]
        if any(query in field for field in haystacks if field):
            if entry["code"] in seen:
                continue
            seen.add(entry["code"])
            matches.append(entry)

    matches.sort(key=lambda item: (item["level"], item["code"]))
    return matches[:20]


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/query_location.py <地区名称或关键词>")
        return 1

    query = " ".join(sys.argv[1:]).strip()
    index = load_index()

    exact = exact_match(index, query)
    if exact:
        print("Exact matches:")
        for entry in exact:
            print_entry(entry)
        return 0

    fuzzy = fuzzy_match(index, query)
    if not fuzzy:
        print(f"No location found for: {query}")
        return 1

    print("Fuzzy matches:")
    for entry in fuzzy:
        print_entry(entry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
