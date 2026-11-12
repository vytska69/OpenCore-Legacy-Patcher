"""
installer_model_check.py: How does a macOS installer decide which Macs it supports?

Reads Apple's public software update catalog, picks the newest full installer
(InstallAssistant) for each requested macOS major version, downloads its small
English Distribution file and reports:
- whether a given board-id / model appears in it
- the installation-check functions that reference board IDs or models

Nothing large is downloaded; the installer payload itself is never fetched.

Usage: python3 ci_tooling/installer_model_check.py --major 15 --board Mac-827FAC58A8FDFA22 --model MacBookAir8,1
"""

import re
import gzip
import plistlib
import argparse
import urllib.request

CATALOG = (
    "https://swscan.apple.com/content/catalogs/others/"
    "index-26-15-14-13-12-10.16-10.15-10.14-10.13-10.12-10.11-10.10-10.9"
    "-mountainlion-lion-snowleopard-leopard.merged-1.sucatalog"
)


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "installer-model-check"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def installers(catalog: dict):
    for product_id, product in catalog.get("Products", {}).items():
        packages = product.get("Packages", [])
        if not any(p.get("URL", "").endswith("InstallAssistant.pkg") for p in packages):
            continue
        dist_url = product.get("Distributions", {}).get("English") or product.get("Distributions", {}).get("en")
        if dist_url:
            yield product_id, product.get("PostDate"), dist_url


def describe(dist: str):
    title = re.search(r"<title>(.*?)</title>", dist, re.S)
    version = re.search(r"<key>VERSION</key>\s*<string>([^<]+)</string>", dist)
    build = re.search(r"<key>BUILD</key>\s*<string>([^<]+)</string>", dist)
    return (title.group(1).strip() if title else "?",
            version.group(1) if version else "?",
            build.group(1) if build else "?")


def board_id_usage(dist: str, board: str):
    """Lines of the installer script that define or use the board-id list"""
    script = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", dist, re.S)) or dist
    lines = script.splitlines()
    names = set()
    for line in lines:
        if re.search(r"Mac-[0-9A-F]{16}", line):
            m = re.match(r"\s*(?:var|let|const)?\s*([A-Za-z_$][\w$]*)\s*=", line)
            if m:
                names.add(m.group(1))
    hits = []
    for number, line in enumerate(lines, 1):
        text = re.sub(r"Mac-[0-9A-F]{16}", "Mac-…", line).strip()
        if (any(re.search(rf"\b{re.escape(n)}\b", line) for n in names) or re.search(r"board", line, re.I)) and len(text) < 400:
            hits.append(f"{number:5}: {text}")
    return sorted(names), hits


def functions_mentioning(dist: str, needles):
    script = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", dist, re.S))
    for match in re.finditer(r"function\s+(\w+)\s*\([^)]*\)\s*\{", script):
        start = match.start()
        depth, i = 0, match.end() - 1
        while i < len(script):
            if script[i] == "{":
                depth += 1
            elif script[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = script[start:i + 1]
        if any(n.lower() in body.lower() for n in needles):
            yield match.group(1), body


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--major", action="append", required=True)
    parser.add_argument("--board", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    catalog = plistlib.loads(fetch(CATALOG))
    found = []
    for product_id, post_date, dist_url in installers(catalog):
        dist = fetch(dist_url).decode("utf-8", "replace")
        title, version, build = describe(dist)
        found.append((post_date, product_id, title, version, build, dist))

    for major in args.major:
        candidates = [f for f in found if f[3].split(".")[0] == major]
        if not candidates:
            print(f"## macOS {major}: no full installer in catalog\n")
            continue
        post_date, product_id, title, version, build, dist = max(candidates, key=lambda f: [int(x) for x in f[3].split(".") if x.isdigit()])
        print(f"## {title} {version} ({build}), product {product_id}\n")
        print(f"- board-id `{args.board}` in Distribution: **{args.board in dist}**")
        print(f"- model `{args.model}` in Distribution: **{args.model in dist}**")
        board_ids = sorted(set(re.findall(r"Mac-[0-9A-F]{16}", dist)))
        models = sorted(set(re.findall(r"\b(?:MacBook(?:Air|Pro)?|Macmini|iMac(?:Pro)?|MacPro)\d+,\d+\b", dist)))
        print(f"- board-ids listed: {len(board_ids)}; models listed: {len(models)}")
        print(f"- board-ids: {', '.join(board_ids)}")
        print()
        names, hits = board_id_usage(dist, args.board)
        print(f"### Script lines defining or using the board-id list (variables: {', '.join(names) or '-'})\n")
        print("```js")
        print("\n".join(hits[:60]) or "(none found)")
        print("```\n")
        script = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", dist, re.S))
        lines = script.splitlines()
        first = next((i for i, l in enumerate(lines) if "virtualBoardID" in l or "supportedBoardIDs" in l), None)
        if first is not None:
            print("### Full compatibility check (board-ids masked)\n")
            print("```js")
            for number in range(max(first - 5, 0), min(first + 160, len(lines))):
                print(f"{number + 1:5}: {re.sub(r'Mac-[0-9A-F]{16}', 'Mac-…', lines[number])[:300]}")
            print("```\n")
        for name, body in functions_mentioning(dist, ["board", "model", "nonSupported", "supported"]):
            print(f"#### function {name}\n```js\n{re.sub(r'Mac-[0-9A-F]{16}', 'Mac-…', body)[:3000]}\n```\n")


if __name__ == "__main__":
    main()
