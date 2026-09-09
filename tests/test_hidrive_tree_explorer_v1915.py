import unittest

import hidrive_tree_explorer_v1915 as tree


class HiDriveTreeExplorerTests(unittest.TestCase):
    def test_folder_labels_always_show_explicit_arrow(self):
        self.assertEqual(tree._folder_label("Fotos", False), "▶ 📁 Fotos")
        self.assertEqual(tree._folder_label("Fotos", True), "▼ 📂 Fotos")

    def test_file_label_has_no_expand_arrow(self):
        self.assertEqual(tree._file_label("bild.jpg"), "📄 bild.jpg")

    def test_node_id_is_stable_and_path_specific(self):
        a1 = tree._node_id("/users/demo/Fotos")
        a2 = tree._node_id("/users/demo/Fotos")
        b = tree._node_id("/users/demo/Dokumente")
        self.assertEqual(a1, a2)
        self.assertNotEqual(a1, b)
        self.assertTrue(a1.startswith("pbv-"))

    def test_parent_remote_never_escapes_home(self):
        home = "/users/demo"
        self.assertEqual(tree._parent_remote("/users/demo/Fotos/2026", home), "/users/demo/Fotos")
        self.assertEqual(tree._parent_remote("/users/demo", home), home)
        self.assertEqual(tree._parent_remote("/users/other", home), home)

    def test_single_selected_folder_becomes_action_target(self):
        current = "/users/demo"
        rows = [{"path": "/users/demo/Fotos", "is_dir": True}]
        self.assertEqual(tree._action_target(current, rows), "/users/demo/Fotos")

    def test_file_or_multiple_selection_keeps_current_target(self):
        current = "/users/demo"
        self.assertEqual(
            tree._action_target(current, [{"path": "/users/demo/a.txt", "is_dir": False}]),
            current,
        )
        self.assertEqual(
            tree._action_target(current, [
                {"path": "/users/demo/Fotos", "is_dir": True},
                {"path": "/users/demo/Dokumente", "is_dir": True},
            ]),
            current,
        )


if __name__ == "__main__":
    unittest.main()
