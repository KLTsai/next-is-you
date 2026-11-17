"""The setup page must know nothing about any hospital (#45, #106).

Every registered hospital's id and display name is searched for in the
frontend source: pages, scripts, types and styles. Hospital knowledge lives in
the registry and reaches the page through the served catalog.

Fixture/mock evidence: reads source files only, no network.
"""

from pathlib import Path

import pytest

from next_is_you.hospital_registry import HOSPITAL_REGISTRY

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
SOURCE_SUFFIXES = {".html", ".ts", ".js", ".css"}


def frontend_source_files() -> list[Path]:
    """Source the browser receives. frontend/test holds synthetic fixtures."""
    files = [
        path
        for path in sorted(FRONTEND.rglob("*"))
        if path.is_file()
        and path.suffix in SOURCE_SUFFIXES
        and path.relative_to(FRONTEND).parts[0] != "test"
    ]
    assert files, "no frontend source found; the scan would pass vacuously"
    return files


def hospital_references(files: list[Path]) -> list[tuple[str, str]]:
    """Return (file name, needle) for each registered id or name found."""
    found = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for hospital_id, entry in HOSPITAL_REGISTRY.items():
            for needle in (hospital_id, entry.display_name):
                if needle in text:
                    found.append((path.name, needle))
    return found


def test_registry_has_hospitals_to_scan_for():
    assert HOSPITAL_REGISTRY
    assert all(entry.display_name for entry in HOSPITAL_REGISTRY.values())


def test_frontend_source_names_no_registered_hospital():
    assert hospital_references(frontend_source_files()) == []


@pytest.mark.parametrize("hospital_id", sorted(HOSPITAL_REGISTRY))
def test_scan_fails_when_a_registered_hospital_id_is_added(hospital_id, tmp_path):
    planted = tmp_path / "organizer-api.d.ts"
    planted.write_text(f'export type Hospital = "{hospital_id}";\n', encoding="utf-8")
    assert hospital_references([planted]) == [(planted.name, hospital_id)]


@pytest.mark.parametrize("hospital_id", sorted(HOSPITAL_REGISTRY))
def test_scan_fails_when_a_registered_display_name_is_added(hospital_id, tmp_path):
    name = HOSPITAL_REGISTRY[hospital_id].display_name
    planted = tmp_path / "main.ts"
    planted.write_text(f'const label = "{name}";\n', encoding="utf-8")
    assert hospital_references([planted]) == [(planted.name, name)]
