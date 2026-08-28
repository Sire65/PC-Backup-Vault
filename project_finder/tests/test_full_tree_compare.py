import hashlib
from pathlib import Path

from project_finder.full_tree_compare import compare_full_tree


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def test_exact_path_and_content_match_is_verified(tmp_path):
    (tmp_path / 'app.py').write_text('app', encoding='utf-8')
    sub = tmp_path / 'cfg'; sub.mkdir()
    (sub / 'settings.json').write_text('cfg', encoding='utf-8')
    result = compare_full_tree(tmp_path, {'app.py': digest('app'), 'cfg/settings.json': digest('cfg')})
    assert result.state == 'EXACT_MATCH'
    assert result.full_tree_verified is True


def test_extra_file_blocks_verification(tmp_path):
    (tmp_path / 'app.py').write_text('app', encoding='utf-8')
    (tmp_path / 'old.py').write_text('old', encoding='utf-8')
    result = compare_full_tree(tmp_path, {'app.py': digest('app')})
    assert result.state == 'EXTRA_FILES'
    assert result.full_tree_verified is False
    assert result.extra == ['old.py']


def test_changed_file_blocks_verification(tmp_path):
    (tmp_path / 'app.py').write_text('new', encoding='utf-8')
    result = compare_full_tree(tmp_path, {'app.py': digest('old')})
    assert result.state == 'CONTENT_DIFFERS'
    assert result.full_tree_verified is False
    assert result.changed == ['app.py']


def test_missing_file_blocks_verification(tmp_path):
    result = compare_full_tree(tmp_path, {'app.py': digest('app')})
    assert result.state == 'MISSING_FILES'
    assert result.full_tree_verified is False


def test_empty_reference_can_never_verify(tmp_path):
    result = compare_full_tree(tmp_path, {})
    assert result.state == 'NO_REFERENCE_MANIFEST'
    assert result.full_tree_verified is False
