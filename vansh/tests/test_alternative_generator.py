from engine.contracts.intent_result import IntentResult, RiskLevel
from engine.alternatives.generator import AlternativeGenerator


def test_file_deletion_alternative():

    result = IntentResult(
        command="find . -type f -delete",
        risk_level=RiskLevel.MEDIUM,
        confidence=0.90,
        intent="Delete all regular files",
        impact="Permanent deletion of files",
        affected_resources=["filesystem"],
        reversible=False,
        requires_confirmation=True,
        explanation="The command deletes files permanently."
    )

    alternative = AlternativeGenerator().generate(result)

    assert alternative.original_command == "find . -type f -delete"
    assert alternative.candidate_command == "find . -type f -print"
    assert alternative.strategy == "Inspect before deletion"


def test_directory_deletion_alternative():

    result = IntentResult(
        command="rm -rf project/",
        risk_level=RiskLevel.HIGH,
        confidence=0.95,
        intent="Remove directory",
        impact="Permanent directory deletion",
        affected_resources=["filesystem"],
        reversible=False,
        requires_confirmation=True,
        explanation="The command permanently deletes a directory."
    )

    alternative = AlternativeGenerator().generate(result)

    assert alternative.candidate_command == "gio trash <target>"
    assert alternative.strategy == "Move to trash"


def test_permission_alternative():

    result = IntentResult(
        command="chmod -R 777 project/",
        risk_level=RiskLevel.HIGH,
        confidence=0.90,
        intent="Change permissions",
        impact="Broad permission modification",
        affected_resources=["filesystem"],
        reversible=True,
        requires_confirmation=True,
        explanation="The command changes permissions recursively."
    )

    alternative = AlternativeGenerator().generate(result)

    assert alternative.candidate_command == "ls -la <target>"
    assert alternative.strategy == "Inspect permissions first"