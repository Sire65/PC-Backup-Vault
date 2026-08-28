from pathlib import Path

from project_finder.scanner import ScanItem
from project_finder.source_candidates import build_source_candidate_rows


def item(path: str, name: str) -> ScanItem:
    return ScanItem(path=path, name=name, extension=Path(name).suffix, size=1, modified=0,
                    modified_iso='1970-01-01 00:00:00', score=80, category='source', duplicate_of='')


def test_no_candidate_from_unrelated_files():
    assert build_source_candidate_rows([item('/x/readme.txt', 'readme.txt')]) == []


def test_candidate_row_is_conservative(tmp_path):
    root = tmp_path / 'vault'; root.mkdir()
    rows = []
    for name in ('app.py', 'ui.py', 'schema.sql'):
        p = root / name; p.write_text('x', encoding='utf-8'); rows.append(item(str(p), name))
    result = build_source_candidate_rows(rows)
    assert len(result) == 1
    assert result[0]['root'] == str(root)
    assert result[0]['required_summary'].endswith('/8')
    assert result[0]['risk'] in {'YELLOW', 'GRAY', 'RED'}
    assert result[0]['risk'] != 'GREEN'
