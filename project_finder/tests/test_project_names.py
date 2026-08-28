from project_finder.project_names import canonical_project


def test_aliases_converge():
    assert canonical_project("Dienstplan") == "DP2 / Dienstplan"
    assert canonical_project("Sire65/Dienstplan") == "DP2 / Dienstplan"
    assert canonical_project("KC-Communication") == "KC Communication"
    assert canonical_project("Sire65/KC-Verwaltung") == "KC Verwaltung"


def test_unknown_name_is_preserved():
    assert canonical_project("Mein Spezialprojekt") == "Mein Spezialprojekt"
