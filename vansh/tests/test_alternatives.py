from engine.alternatives.templates import ALTERNATIVE_TEMPLATES


def test_file_deletion_template_exists():
    template = ALTERNATIVE_TEMPLATES["file_deletion"]

    assert template.name == "Inspect before deletion"
    assert "find" in template.example_command


def test_directory_deletion_template_exists():
    template = ALTERNATIVE_TEMPLATES["directory_deletion"]

    assert template.name == "Move to trash"
    assert "gio trash" in template.example_command


def test_permission_template_exists():
    template = ALTERNATIVE_TEMPLATES["permission_change"]

    assert template.name == "Inspect permissions first"


def test_disk_template_exists():
    template = ALTERNATIVE_TEMPLATES["disk_operation"]

    assert template.name == "Inspect target device"