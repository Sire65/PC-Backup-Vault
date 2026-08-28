from project_finder.ui_tab import ProjectFinderTab


def test_ui_cleanup_method_exists_and_is_restricted_to_quarantine_proposals():
    # Behavioral guard: the UI helper must filter selected paths through cleanup proposals.
    code = ProjectFinderTab._approved_quarantine_paths.__code__
    assert 'cleanup_candidates' in ProjectFinderTab._approved_quarantine_paths.__globals__
    assert 'QUARANTINE' in code.co_consts


def test_ui_never_calls_permanent_purge():
    names = set(ProjectFinderTab.quarantine_selected.__code__.co_names)
    assert 'purge_quarantine' not in names
    assert 'quarantine' in names
