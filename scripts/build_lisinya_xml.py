#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE_URL = "https://www.lisinya.com/storage/cache/feed/0-lisinyakitap.xml"
SOURCE_FILE = Path("kaynak.xml")
OUTPUT_FILE = Path("public/lisinyakitap-guncel-v2.xml")

FOOTER = (
    "Ürün, Kuzgun Ticaret tarafından özenle paketlenerek "
    "adınıza düzenlenen faturasıyla gönderilir."
)

FORBIDDEN = [
    ("AV", re.compile(r"(?<!\w)AV(?!\w)", re.IGNORECASE)),
    ("SİLAH", re.compile(r"(?<!\w)S[Iİ]LAH(?!\w)", re.IGNORECASE)),
    ("TETİK", re.compile(r"(?<!\w)TET[Iİ]K(?!\w)", re.IGNORECASE)),
    ("NAMLU", re.compile(r"(?<!\w)NAMLU(?!\w)", re.IGNORECASE)),
    (
        "NATIONAL GEOGRAPHIC",
        re.compile(
            r"(?<!\w)NATIONAL\s+GEOGRAPHIC(?!\w)",
            re.IGNORECASE,
        ),
    ),
]

LISINYA_PATTERNS = [
    re.compile(
        r"Ürün\s+Markası\s*:\s*Lisinya(?:\s+Kitap)?",
        re.IGNORECASE,
    ),
    re.compile(r"\bTRY\s+Lisinya\s+Kitap\b", re.IGNORECASE),
    re.compile(r"\bLisinya\s+Kitap\b", re.IGNORECASE),
    re.compile(r"\bLisinya\b", re.IGNORECASE),
]


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def clean_text(value: str, counts: dict[str, int]) -> str:
    for pattern in LISINYA_PATTERNS:
        value, count = pattern.subn("", value)
        counts["LISINYA"] += count

    for name, pattern in FORBIDDEN:
        value, count = pattern.subn("", value)
        counts[name] += count

    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"\s+(<br\s*/?>)", r"\1", value, flags=re.I)
    return value.strip(" -|:")


def download_xml() -> None:
    print("Kaynak XML indiriliyor...")
    urllib.request.urlretrieve(SOURCE_URL, SOURCE_FILE)
    print("Kaynak XML indirildi.")


def transform_xml() -> dict[str, int]:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    counts = {name: 0 for name, _ in FORBIDDEN}
    counts.update(
        {
            "LISINYA": 0,
            "K0707": 0,
            "MARKA_NO_NAME": 0,
            "FOOTER_EKLENDI": 0,
        }
    )

    tree = ET.parse(SOURCE_FILE)
    root = tree.getroot()

    for element in root.iter():
        tag = local_name(element.tag)
        value = element.text or ""

        if tag in {"barkod", "model"}:
            cleaned, count = re.subn(
                r"-k0707$",
                "",
                value.strip(),
                flags=re.IGNORECASE,
            )
            element.text = cleaned
            counts["K0707"] += count

        elif tag == "name":
            element.text = clean_text(value, counts)

        elif tag == "description":
            cleaned = clean_text(value, counts)
            if FOOTER.casefold() not in cleaned.casefold():
                cleaned = f"{cleaned} {FOOTER}".strip()
                counts["FOOTER_EKLENDI"] += 1
            element.text = cleaned

        elif tag == "brand" and re.search(
            r"\blisinya\b",
            value,
            flags=re.IGNORECASE,
        ):
            cleaned = clean_text(value, counts)
            element.text = cleaned or "No Name"
            if not cleaned:
                counts["MARKA_NO_NAME"] += 1

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True,
        short_empty_elements=True,
    )

    return counts


def validate_xml() -> None:
    products = 0
    barcodes = 0
    suffixes = 0
    forbidden_hits = []
    footer_missing = 0

    forbidden_patterns = [
        pattern for _, pattern in FORBIDDEN
    ] + [re.compile(r"\blisinya\b", re.IGNORECASE)]

    for _, element in ET.iterparse(OUTPUT_FILE, events=("end",)):
        tag = local_name(element.tag)
        value = element.text or ""

        if tag == "product":
            products += 1

        elif tag == "barkod":
            barcodes += 1
            if value.lower().endswith("-k0707"):
                suffixes += 1

        elif tag == "model" and value.lower().endswith("-k0707"):
            suffixes += 1

        elif tag == "description":
            if FOOTER.casefold() not in value.casefold():
                footer_missing += 1

        if tag in {"name", "description", "brand"}:
            for pattern in forbidden_patterns:
                if pattern.search(value):
                    forbidden_hits.append(
                        f"{tag}: {pattern.pattern}"
                    )

        element.clear()

    size = os.path.getsize(OUTPUT_FILE)

    if products < 10000:
        raise RuntimeError(
            f"Beklenmeyen ürün sayısı: {products}"
        )

    if barcodes != products:
        raise RuntimeError(
            f"Ürün/barkod sayısı uyuşmuyor: {products}/{barcodes}"
        )

    if suffixes:
        raise RuntimeError(
            f"Temizlenmemiş -k0707 sayısı: {suffixes}"
        )

    if forbidden_hits:
        raise RuntimeError(
            f"Temizlenmemiş ifadeler: {forbidden_hits[:20]}"
        )

    if footer_missing:
        raise RuntimeError(
            f"Açıklama cümlesi eksik ürün sayısı: {footer_missing}"
        )

    if size < 10_000_000:
        raise RuntimeError(
            f"XML beklenenden küçük: {size} bayt"
        )

    print(
        f"Doğrulama tamamlandı: {products} ürün, "
        f"{barcodes} barkod, {size} bayt"
    )


def main() -> int:
    start_time = time.time()

    try:
        print("Kuzgun XML Engine v2 başlatıldı.")
        download_xml()
        counts = transform_xml()
        validate_xml()

        elapsed = time.time() - start_time
        create_report(counts, elapsed)

        print("İşlem tamamlandı.")
        print("Temizlik özeti:", counts)
        print("Rapor oluşturuldu: public/rapor.html")
        return 0

    except Exception as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1


def create_report(counts: dict[str, int], elapsed: float) -> None:
    products = 0

    for _, element in ET.iterparse(OUTPUT_FILE, events=("end",)):
        if local_name(element.tag) == "product":
            products += 1
        element.clear()

    size = OUTPUT_FILE.stat().st_size

    report = f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<title>Kuzgun XML Engine v2</title>
<style>
body {{ font-family: Arial, sans-serif; background: #f5f5f5; padding: 40px; }}
table {{ border-collapse: collapse; background: white; }}
td {{ padding: 10px 20px; border: 1px solid #ddd; }}
h1 {{ color: #ff6600; }}
</style>
</head>
<body>
<h1>Kuzgun XML Engine v2</h1>
<table>
<tr><td>Toplam Ürün</td><td>{products}</td></tr>
<tr><td>Lisinya Temizlenen</td><td>{counts["LISINYA"]}</td></tr>
<tr><td>No Name Marka</td><td>{counts["MARKA_NO_NAME"]}</td></tr>
<tr><td>K0707 Temizlenen</td><td>{counts["K0707"]}</td></tr>
<tr><td>Açıklama Eklenen</td><td>{counts["FOOTER_EKLENDI"]}</td></tr>
<tr><td>XML Boyutu</td><td>{size:,} byte</td></tr>
<tr><td>İşlem Süresi</td><td>{elapsed:.2f} saniye</td></tr>
</table>
</body>
</html>
"""

    Path("public/rapor.html").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
