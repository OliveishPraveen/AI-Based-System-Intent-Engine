from dataclasses import dataclass


@dataclass(frozen=True)
class AlternativeTemplate:
    """
    Defines a safer strategy for a class of operations.
    """

    name: str
    description: str
    example_command: str


ALTERNATIVE_TEMPLATES = {
    "file_deletion": AlternativeTemplate(
        name="Inspect before deletion",
        description=(
            "List matching files first so the user can review "
            "what will be affected before deleting anything."
        ),
        example_command="find . -type f -print",
    ),

    "directory_deletion": AlternativeTemplate(
        name="Move to trash",
        description=(
            "Move the target to the desktop trash instead of "
            "permanently deleting it."
        ),
        example_command="gio trash <target>",
    ),

    "permission_change": AlternativeTemplate(
        name="Inspect permissions first",
        description=(
            "Inspect current permissions before applying a "
            "recursive or broad permission change."
        ),
        example_command="ls -la <target>",
    ),

    "disk_operation": AlternativeTemplate(
        name="Inspect target device",
        description=(
            "Verify the target device before performing a "
            "destructive disk operation."
        ),
        example_command="lsblk",
    ),
}