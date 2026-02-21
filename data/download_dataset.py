"""
Download Brazilian STJ court decisions from the Open Data Portal.
Usage: python data/download_dataset.py --output-dir data/raw --start-date 2023-01-01 --end-date 2024-12-31 --max-documents 1225
"""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import requests
from tqdm import tqdm

STJ_API_BASE = "https://dadosabertos.web.stj.jus.br"
STJ_JURISPRUDENCIA_ENDPOINT = f"{STJ_API_BASE}/api/3/action/datastore_search"

# Default page size for API requests
_PAGE_SIZE = 100


def download_decisions(
    output_dir: str,
    start_date: str = "2023-01-01",
    end_date: str = "2024-12-31",
    max_documents: int = 1225,
    resource_id: str = "jurisprudencia",
    delay_between_requests: float = 0.5,
) -> list[dict]:
    """
    Download court decisions from STJ Open Data Portal.

    Args:
        output_dir: Directory to save downloaded documents.
        start_date: Start date filter (YYYY-MM-DD).
        end_date: End date filter (YYYY-MM-DD).
        max_documents: Maximum number of documents to download.
        resource_id: STJ dataset resource ID.
        delay_between_requests: Seconds to wait between API calls (rate limiting).

    Returns:
        List of downloaded document dicts.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    documents: list[dict] = []
    offset = 0

    with tqdm(total=max_documents, desc="Downloading decisions") as pbar:
        while len(documents) < max_documents:
            limit = min(_PAGE_SIZE, max_documents - len(documents))
            params: dict = {
                "resource_id": resource_id,
                "limit": limit,
                "offset": offset,
                "filters": json.dumps(
                    {
                        "DATA_PUBLICACAO": {
                            "$gte": start_date,
                            "$lte": end_date,
                        }
                    }
                ),
            }

            try:
                response = requests.get(
                    STJ_JURISPRUDENCIA_ENDPOINT,
                    params=params,
                    timeout=30,
                )
                response.raise_for_status()
                result = response.json()
            except (requests.RequestException, json.JSONDecodeError) as exc:
                print(f"Request failed at offset {offset}: {exc}")
                break

            records = result.get("result", {}).get("records", [])
            if not records:
                break

            documents.extend(records)
            pbar.update(len(records))
            offset += len(records)

            # Stop if API returned fewer records than requested (end of dataset)
            if len(records) < limit:
                break

            time.sleep(delay_between_requests)

    return documents[:max_documents]


def _text_fingerprint(doc: dict) -> str:
    """Create a short fingerprint for a document based on its textual content."""
    text = " ".join(str(v) for v in doc.values() if v)
    return hashlib.md5(text.encode("utf-8")).hexdigest()  # noqa: S324 – used for dedup, not security


def apply_diversity_filter(
    documents: list[dict],
    similarity_threshold: float = 0.15,
) -> list[dict]:
    """
    Apply a simple hash-based deduplication filter to reduce near-duplicate documents.

    Uses MD5 fingerprints of combined field text.  For a more robust filter the
    caller may pass ``similarity_threshold`` which is stored for future use with
    TF-IDF cosine similarity, but the current implementation uses exact-fingerprint
    deduplication which is an effective baseline.

    Args:
        documents: List of document dicts.
        similarity_threshold: Reserved for future TF-IDF similarity filtering.

    Returns:
        Deduplicated list of documents.
    """
    seen: set[str] = set()
    unique: list[dict] = []
    for doc in documents:
        fp = _text_fingerprint(doc)
        if fp not in seen:
            seen.add(fp)
            unique.append(doc)
    return unique


def save_documents(documents: list[dict], output_dir: str) -> None:
    """Save each document as a separate JSON file."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    for i, doc in enumerate(tqdm(documents, desc="Saving documents")):
        # Use record ID if available, otherwise use index
        doc_id = doc.get("_id") or doc.get("NUMERO_REGISTRO") or str(i)
        filename = Path(output_dir) / f"{doc_id}.json"
        with open(filename, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download STJ court decisions from the Open Data Portal."
    )
    parser.add_argument("--output-dir", default="data/raw", help="Output directory")
    parser.add_argument("--start-date", default="2023-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", default="2024-12-31", help="End date YYYY-MM-DD")
    parser.add_argument("--max-documents", type=int, default=1225, help="Max documents")
    parser.add_argument("--resource-id", default="jurisprudencia", help="STJ resource ID")
    parser.add_argument(
        "--delay", type=float, default=0.5, help="Delay between requests (seconds)"
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.15,
        help="Similarity threshold for diversity filter",
    )
    args = parser.parse_args()

    print(f"Downloading up to {args.max_documents} decisions from {args.start_date} to {args.end_date}…")
    documents = download_decisions(
        output_dir=args.output_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        max_documents=args.max_documents,
        resource_id=args.resource_id,
        delay_between_requests=args.delay,
    )
    print(f"Downloaded {len(documents)} documents.")

    documents = apply_diversity_filter(documents, similarity_threshold=args.similarity_threshold)
    print(f"After diversity filter: {len(documents)} documents.")

    save_documents(documents, args.output_dir)
    print(f"Saved to {args.output_dir}/")


if __name__ == "__main__":
    main()
