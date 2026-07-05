#!/usr/bin/env python3
import argparse
import sys

from tqdm import tqdm

from scout.export import export_results
from scout.pipeline import evaluate_businesses, find_businesses


def parse_args():
    parser = argparse.ArgumentParser(description="Website-Scouting-Tool: findet Firmen ohne/mit veralteter Website.")
    parser.add_argument("--branche", action="append", required=True, help="Branche (mehrfach angebbar), z.B. --branche Friseur --branche Restaurant")
    parser.add_argument("--ort", default="Bayreuth", help="Ort/Stadt (Default: Bayreuth)")
    parser.add_argument("--radius", type=int, default=5000, help="Suchradius in Metern (Default: 5000)")
    parser.add_argument("--min-score", type=int, default=0, help="Minimaler Score fÃ¼r den Export (Default: 0 = alles)")
    parser.add_argument("--output", default="ergebnis.xlsx", help="Ausgabedatei (.xlsx oder .csv)")
    parser.add_argument("--source", default="osm", choices=["osm", "google"], help="Datenquelle (Default: osm)")
    parser.add_argument("--limit", type=int, default=None, help="Optional: maximale Anzahl Firmen verarbeiten (fÃ¼r Testlaeufe)")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.source == "google":
        print("Fehler: Google Places Connector ist noch nicht implementiert (v1 nutzt nur OSM).", file=sys.stderr)
        sys.exit(1)

    print(f"Suche Firmen fÃ¼r Branche(n) {args.branche} in {args.ort} (Radius {args.radius}m) Ã¼ber OSM ...")
    businesses = find_businesses(args.branche, args.ort, args.radius)
    print(f"Nach Deduplizierung: {len(businesses)} Firmen")

    if args.limit:
        businesses = businesses[: args.limit]
        print(f"Begrenzt auf --limit {args.limit} Firmen")

    csv_path = args.output.rsplit(".", 1)[0] + "_raw.csv"
    progress_bar = tqdm(total=len(businesses), desc="PrÃ¼fe Websites")

    def on_progress(i, total, name):
        progress_bar.update(1)

    rows = evaluate_businesses(businesses, csv_path=csv_path, on_progress=on_progress)
    progress_bar.close()

    export_results(rows, args.output, args.min_score)
    print(f"Fertig. Rohdaten: {csv_path}, Export: {args.output}")


if __name__ == "__main__":
    main()
