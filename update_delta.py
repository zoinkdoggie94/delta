#!/usr/bin/env python3

import json
import os
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests


OUTPUT_FILE = "delta.json"

OFFICIAL_PAGES = [
    "https://deltaexploits.gg/delta-executor-ios",
    "https://deltaexploits.dev/delta-executor-ios",
]

CDN_BASE = "https://cdn.glopdelivery.com/file"

ICON_URL = "https://cdn.weao.gg/slug/delta/logo.png"

SCREENSHOTS = [
    "https://cdn.weao.gg/slug/delta/screenshot1.png",
    "https://cdn.weao.gg/slug/delta/screenshot2.png",
    "https://cdn.weao.gg/slug/delta/screenshot3.png",
    "https://cdn.weao.gg/slug/delta/screenshot4.png",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/141.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

TIMEOUT = 25

session = requests.Session()
session.headers.update(HEADERS)


class ScriptParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "script":
            return

        attrs = dict(attrs)
        src = attrs.get("src")

        if src:
            self.scripts.append(src)


def version_tuple(version):
    numbers = re.findall(r"\d+", str(version))

    if not numbers:
        return (0,)

    return tuple(int(number) for number in numbers)


def extract_delta_downloads(text):
    if not text:
        return []

    normalized = (
        text.replace("\\/", "/")
        .replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("&amp;", "&")
    )

    found = {}

    full_url_pattern = re.compile(
        r"https://cdn\.glopdelivery\.com/file/"
        r"Delta-([0-9]+(?:\.[0-9]+)+)\.ipa",
        re.IGNORECASE,
    )

    filename_pattern = re.compile(
        r"Delta-([0-9]+(?:\.[0-9]+)+)\.ipa",
        re.IGNORECASE,
    )

    for match in full_url_pattern.finditer(normalized):
        version = match.group(1)
        url = match.group(0)
        found[version] = url

    for match in filename_pattern.finditer(normalized):
        version = match.group(1)

        if version not in found:
            found[version] = f"{CDN_BASE}/Delta-{version}.ipa"

    return [
        {
            "version": version,
            "url": url,
        }
        for version, url in found.items()
    ]


def get_page(url):
    response = session.get(
        url,
        timeout=TIMEOUT,
        allow_redirects=True,
    )

    response.raise_for_status()

    return response


def find_from_official_page(page_url):
    print(f"Checking official Delta page: {page_url}")

    try:
        response = get_page(page_url)
    except Exception as exc:
        print(f"Warning: failed to fetch {page_url}: {exc}")
        return []

    html = response.text

    candidates = extract_delta_downloads(html)

    if candidates:
        print(
            f"Found {len(candidates)} Delta IPA candidate(s) "
            f"directly inside {page_url}"
        )

    parser = ScriptParser()

    try:
        parser.feed(html)
    except Exception as exc:
        print(f"Warning: could not completely parse HTML: {exc}")

    script_urls = []

    for src in parser.scripts:
        absolute = urljoin(response.url, src)

        if absolute not in script_urls:
            script_urls.append(absolute)

    preferred_scripts = []
    other_scripts = []

    for script_url in script_urls:
        lowered = script_url.lower()

        if (
            "delta-executor-ios" in lowered
            or "delta" in lowered
            or "_next/static/chunks/pages/" in lowered
            or "_next/static/chunks/app/" in lowered
        ):
            preferred_scripts.append(script_url)
        else:
            other_scripts.append(script_url)

    scripts_to_check = preferred_scripts + other_scripts
    scripts_to_check = scripts_to_check[:80]

    for index, script_url in enumerate(scripts_to_check, start=1):
        try:
            script_response = session.get(
                script_url,
                timeout=TIMEOUT,
                allow_redirects=True,
                headers={
                    **HEADERS,
                    "Referer": response.url,
                    "Accept": "*/*",
                },
            )

            if not script_response.ok:
                continue

            matches = extract_delta_downloads(script_response.text)

            if matches:
                print(
                    "Found Delta IPA reference in "
                    f"JS chunk {index}/{len(scripts_to_check)}"
                )

                candidates.extend(matches)

        except Exception as exc:
            print(
                "Warning: failed checking JS chunk "
                f"{script_url}: {exc}"
            )

    unique = {}

    for candidate in candidates:
        version = candidate["version"]
        url = candidate["url"]

        unique[version] = {
            "version": version,
            "url": url,
        }

    return list(unique.values())


def find_latest_delta():
    all_candidates = []

    for page in OFFICIAL_PAGES:
        candidates = find_from_official_page(page)

        all_candidates.extend(candidates)

        if candidates:
            break

    unique = {}

    for candidate in all_candidates:
        unique[candidate["version"]] = candidate

    candidates = list(unique.values())

    if not candidates:
        raise RuntimeError(
            "Could not find a Delta iOS IPA on either "
            "official Delta site."
        )

    candidates.sort(
        key=lambda item: version_tuple(item["version"]),
        reverse=True,
    )

    latest = candidates[0]

    print(
        "Latest Delta candidate: "
        f"{latest['version']} -> {latest['url']}"
    )

    return latest


def verify_download(url):
    print(f"Verifying IPA URL: {url}")

    try:
        response = session.get(
            url,
            timeout=TIMEOUT,
            allow_redirects=True,
            stream=True,
            headers={
                **HEADERS,
                "Range": "bytes=0-0",
                "Accept": "*/*",
            },
        )

        status = response.status_code

        content_type = (
            response.headers
            .get("Content-Type", "")
            .lower()
        )

        if status not in (200, 206):
            response.close()

            raise RuntimeError(
                f"IPA returned unexpected HTTP status {status}"
            )

        if "text/html" in content_type:
            response.close()

            raise RuntimeError(
                "IPA URL returned HTML instead of an IPA file."
            )

        response.close()

        print(
            f"IPA URL verified successfully (HTTP {status})."
        )

    except Exception as exc:
        raise RuntimeError(
            f"Could not verify the Delta IPA URL: {exc}"
        ) from exc


def get_remote_size(url):
    print("Checking IPA size...")

    try:
        response = session.get(
            url,
            timeout=TIMEOUT,
            allow_redirects=True,
            stream=True,
            headers={
                **HEADERS,
                "Range": "bytes=0-0",
                "Accept": "*/*",
            },
        )

        content_range = response.headers.get(
            "Content-Range",
            "",
        )

        match = re.search(
            r"/(\d+)$",
            content_range,
        )

        if match:
            size = int(match.group(1))
            response.close()

            print(
                f"IPA size from Content-Range: {size} bytes"
            )

            return size

        content_length = response.headers.get(
            "Content-Length"
        )

        if content_length:
            try:
                size = int(content_length)

                if response.status_code == 200 and size > 0:
                    response.close()

                    print(
                        f"IPA size from Content-Length: {size} bytes"
                    )

                    return size

            except ValueError:
                pass

        response.close()

    except Exception as exc:
        print(
            f"Warning: range request could not determine size: {exc}"
        )

    try:
        response = session.head(
            url,
            timeout=TIMEOUT,
            allow_redirects=True,
            headers={
                **HEADERS,
                "Accept": "*/*",
            },
        )

        if response.ok:
            content_length = response.headers.get(
                "Content-Length"
            )

            if content_length:
                size = int(content_length)

                if size > 0:
                    print(
                        f"IPA size from HEAD: {size} bytes"
                    )

                    return size

    except Exception as exc:
        print(
            f"Warning: HEAD request could not determine size: {exc}"
        )

    print(
        "Warning: IPA size unavailable. Using 0."
    )

    return 0


def load_existing_source():
    if not os.path.exists(OUTPUT_FILE):
        return None

    try:
        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError(
                "Root of delta.json is not an object."
            )

        return data

    except Exception as exc:
        raise RuntimeError(
            f"Existing {OUTPUT_FILE} is invalid; "
            f"refusing to overwrite it: {exc}"
        ) from exc


def get_existing_versions(source):
    if not source:
        return []

    apps = source.get("apps")

    if not isinstance(apps, list) or not apps:
        return []

    app = apps[0]

    if not isinstance(app, dict):
        return []

    versions = app.get("versions")

    if not isinstance(versions, list):
        return []

    valid_versions = []

    for version in versions:
        if not isinstance(version, dict):
            continue

        if not version.get("version"):
            continue

        if not version.get("downloadURL"):
            continue

        valid_versions.append(version)

    return valid_versions


def create_source(versions):
    return {
        "name": "Shrubbery's Delta Source",
        "subtitle": "Created and maintained by Shrubbery",
        "description": (
            "An unofficial auto-updating AltStore, "
            "SideStore and Feather source for Delta "
            "Executor on iOS. This source was created "
            "and is maintained by Shrubbery / ShrubHub. "
            "Delta itself is developed separately by "
            "the Delta team. App files are downloaded "
            "from Delta's own distribution servers."
        ),
        "website": "https://deltaexploits.gg/",
        "iconURL": ICON_URL,
        "tintColor": "#335FFF",
        "featuredApps": [
            "com.gloop.deltamobile"
        ],
        "apps": [
            {
                "name": "Delta",
                "bundleIdentifier": "com.gloop.deltamobile",
                "developerName": "Delta Exploits",
                "subtitle": "Delta Executor for iOS",
                "localizedDescription": (
                    "Delta Executor for iOS. This "
                    "unofficial AltStore-style source "
                    "was created and is maintained by "
                    "Shrubbery / ShrubHub and "
                    "automatically tracks new Delta "
                    "iOS releases from Delta's "
                    "distribution pages."
                ),
                "iconURL": ICON_URL,
                "tintColor": "#335FFF",
                "category": "games",
                "screenshots": {
                    "iphone": SCREENSHOTS
                },
                "versions": versions,
            }
        ],
    }


def write_source(source):
    new_text = json.dumps(
        source,
        indent=2,
        ensure_ascii=False,
    ) + "\n"

    old_text = None

    if os.path.exists(OUTPUT_FILE):
        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            old_text = file.read()

    if old_text == new_text:
        print(
            f"{OUTPUT_FILE} already matches the generated source."
        )

        return False

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        file.write(new_text)

    print(
        f"Wrote updated {OUTPUT_FILE}"
    )

    return True


def main():
    existing_source = load_existing_source()

    existing_versions = get_existing_versions(
        existing_source
    )

    latest = find_latest_delta()

    latest_version = latest["version"]
    latest_url = latest["url"]

    verify_download(latest_url)

    if existing_versions:
        newest_existing = max(
            existing_versions,
            key=lambda item: version_tuple(
                item.get("version", "0")
            ),
        )

        newest_existing_version = newest_existing.get(
            "version",
            "0",
        )

        if (
            version_tuple(latest_version)
            <
            version_tuple(newest_existing_version)
        ):
            print(
                "WARNING: official site returned "
                "an older Delta version "
                f"({latest_version}) than "
                "delta.json already contains "
                f"({newest_existing_version})."
            )

            print(
                "Refusing to downgrade the source. "
                "No changes will be made."
            )

            return 0

    matching_existing = None

    for item in existing_versions:
        if item.get("version") == latest_version:
            matching_existing = item
            break

    if matching_existing:
        print(
            f"Delta {latest_version} is already "
            f"present in {OUTPUT_FILE}."
        )

        if matching_existing.get("downloadURL") != latest_url:
            print(
                "Updating the existing version's download URL."
            )

            matching_existing["downloadURL"] = latest_url

        current_size = matching_existing.get(
            "size",
            0,
        )

        if not isinstance(current_size, int) or current_size <= 0:
            size = get_remote_size(
                latest_url
            )

            if size > 0:
                matching_existing["size"] = size

        versions = existing_versions

    else:
        print(
            f"New Delta release detected: {latest_version}"
        )

        size = get_remote_size(
            latest_url
        )

        now = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

        new_version = {
            "version": latest_version,
            "date": now,
            "localizedDescription": (
                f"Updated to Delta {latest_version}. "
                "Source maintained by Shrubbery / ShrubHub."
            ),
            "downloadURL": latest_url,
            "size": size,
        }

        versions = [
            new_version,
            *existing_versions,
        ]

    seen_versions = set()
    cleaned_versions = []

    for item in versions:
        version = str(
            item.get(
                "version",
                "",
            )
        ).strip()

        if not version:
            continue

        if version in seen_versions:
            continue

        seen_versions.add(version)

        cleaned_versions.append(item)

    cleaned_versions.sort(
        key=lambda item: version_tuple(
            item.get(
                "version",
                "0",
            )
        ),
        reverse=True,
    )

    source = create_source(
        cleaned_versions
    )

    changed = write_source(source)

    print()
    print("========================================")
    print("Shrubbery's Delta Source")
    print("Created and maintained by Shrubbery / ShrubHub")
    print(f"Latest Delta: {latest_version}")
    print(f"IPA: {latest_url}")
    print(f"Versions stored: {len(cleaned_versions)}")
    print(f"Changed: {'yes' if changed else 'no'}")
    print("========================================")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())

    except Exception as exc:
        print()

        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        sys.exit(1)
