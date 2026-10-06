import argparse
import json
from datetime import datetime
from pathlib import Path

from .engine.engine import ROOT, evaluate
from .engine.extracts import read_extract
from .pipeline import Pipeline
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="Evaluate BaNCS extracts with the Python SLA engine without changing application data.")
    parser.add_argument("directory", type=Path, nargs="?", default=ROOT / "Claude_Data")
    parser.add_argument("--format", choices=("csv", "xlsx"), default="csv")
    parser.add_argument("--as-of", help="Explicit extract date (YYYY-MM-DD)")
    parser.add_argument("--load-data", action="store_true", help="Import CSV extracts and build persisted packs")
    parser.add_argument("--data-dir", type=Path, help="Explicit output directory required with --load-data")
    args = parser.parse_args()
    if args.load_data:
        if args.data_dir is None:
            parser.error("--load-data requires --data-dir; use a separate directory from the running Node backend")
        if args.format != "csv" or args.as_of:
            parser.error("--load-data uses CSV extracts and their derived extract date")
        store = Store(args.data_dir, bundled_dir=args.directory)
        active_data_dir = Store().data_dir.resolve()
        if store.data_dir == active_data_dir:
            parser.error("--data-dir must differ from the active application's DATA_DIR during migration")
        try:
            snapshot = Pipeline(store).load_bundled()
        except (ValueError, OSError) as error:
            parser.error(str(error))
        if snapshot is None:
            parser.error(f"No CSV extracts found in {args.directory}")
        print(json.dumps(snapshot, indent=2))
        return
    if args.data_dir is not None:
        parser.error("--data-dir is only used with --load-data")
    if args.as_of:
        try:
            datetime.strptime(args.as_of, "%Y-%m-%d")
        except ValueError:
            parser.error("--as-of must be a valid YYYY-MM-DD date")
    files = sorted(args.directory.glob(f"*.{args.format}"))
    files = [file for file in files if not file.name.startswith("SLA_Expected")]
    if not files:
        parser.error(f"No .{args.format} extracts found in {args.directory}")
    try:
        result = evaluate([read_extract(file.read_bytes(), file.name) for file in files], as_of=args.as_of)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps({"asOf": result["asOf"], "asOfSource": result["asOfSource"],
                      "itemCount": len(result["items"]), "monthly": result["monthly"], "totals": result["totals"]}, indent=2))


if __name__ == "__main__":
    main()
