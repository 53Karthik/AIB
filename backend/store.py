import json
import os
import re
import tempfile
from pathlib import Path

from .engine.engine import ROOT


MONTH_FULL = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def is_month_key(value):
    return re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(value)) is not None


def month_label(month):
    year, number = map(int, month.split("-"))
    return f"{MONTH_FULL[number - 1]} {year}"


def day_label(day):
    if not day:
        return None
    year, month, number = map(int, day.split("-"))
    return f"{number} {MONTH_FULL[month - 1]} {year}"


class Store:
    def __init__(self, data_dir=None, bundled_dir=None):
        configured = data_dir if data_dir is not None else os.environ.get("DATA_DIR")
        self.data_dir = Path(configured).resolve() if configured else ROOT / "data"
        self.extracts_dir = self.data_dir / "extracts"
        self.analyses_dir = self.data_dir / "analyses"
        self.bundled_dir = Path(bundled_dir) if bundled_dir is not None else ROOT / "Claude_Data"

    def _read_json(self, path, fallback):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return fallback

    def _write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(value, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                stream.write("\n")
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return value

    def _extract_path(self, stored):
        if not stored or str(stored) in (".", "..") or "/" in str(stored) or "\\" in str(stored) or ":" in str(stored):
            raise ValueError("Invalid stored extract filename")
        path = (self.extracts_dir / stored).resolve()
        if path.parent != self.extracts_dir.resolve():
            raise ValueError("Extract path must stay inside the extracts directory")
        return path

    def _analysis_path(self, month):
        if not is_month_key(month):
            raise ValueError("Invalid reporting month")
        return self.analyses_dir / f"{month}.json"

    def read_extract_index(self):
        return self._read_json(self.extracts_dir / "_index.json", [])

    def write_extract_index(self, entries):
        return self._write_json(self.extracts_dir / "_index.json", entries)

    def save_extract_file(self, identifier, original_name, buffer):
        extension = original_name.rsplit(".", 1)[-1].lower() or "bin"
        stored = f"{identifier}.{extension}"
        path = self._extract_path(stored)
        self.extracts_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buffer)
        return stored

    def read_extract_file(self, stored):
        return self._extract_path(stored).read_bytes()

    def delete_extract_file(self, stored):
        self._extract_path(stored).unlink(missing_ok=True)

    def read_analysis(self, month):
        return self._read_json(self._analysis_path(month), None)

    def write_analysis(self, month, analysis):
        return self._write_json(self._analysis_path(month), analysis)

    def list_months(self):
        if not self.analyses_dir.exists():
            return []
        return sorted((path.stem for path in self.analyses_dir.glob("*.json") if is_month_key(path.stem)), reverse=True)

    def clear_analyses(self):
        for path in self.analyses_dir.glob("*.json"):
            path.unlink()

    def read_snapshot(self):
        return self._read_json(self.data_dir / "snapshot.json", None)

    def write_snapshot(self, snapshot):
        return self._write_json(self.data_dir / "snapshot.json", snapshot)

    def clear_snapshot(self):
        (self.data_dir / "snapshot.json").unlink(missing_ok=True)

    def list_bundled_extracts(self, extension="csv"):
        if not self.bundled_dir.exists():
            return []
        return [{"name": path.name, "absolute": path} for path in sorted(self.bundled_dir.iterdir())
                if path.is_file() and path.name.lower().endswith(f".{extension}")
                and not path.name.lower().startswith("sla_expected_results")]
