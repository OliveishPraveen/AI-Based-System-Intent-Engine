from engine.contracts.intent_result import IntentResult
from engine.contracts.alternative_result import AlternativeResult
from engine.alternatives.templates import ALTERNATIVE_TEMPLATES


class AlternativeGenerator:
    """
    Generates safer command alternatives from an IntentResult.
    Returns None if no known safe strategy exists for the command.
    """

    def generate(self, result: IntentResult) -> AlternativeResult | None:
        try:
            strategy = self._select_strategy(result)
        except ValueError:
            return None

        template = ALTERNATIVE_TEMPLATES[strategy]

        return AlternativeResult(
            original_command=result.command,
            candidate_command=template.example_command,
            intent=result.intent,
            strategy=template.name,
            explanation=template.description,
        )

    def _select_strategy(self, result: IntentResult) -> str:
        text = (
            result.command
            + " "
            + result.intent
            + " "
            + result.impact
            + " "
            + result.explanation
        ).lower()

        if (
            "-delete" in text
            or "delete files" in text
            or "deletes files" in text
            or "deleting files" in text
        ):
            return "file_deletion"

        if (
            "rm -rf" in text
            or "remove directory" in text
            or "delete directory" in text
            or "deleting directory" in text
        ):
            return "directory_deletion"

        if (
            "chmod" in text
            or "permission" in text
            or "permissions" in text
        ):
            return "permission_change"

        if (
            "mkfs" in text
            or "format disk" in text
            or "raw device" in text
            or "disk operation" in text
        ):
            return "disk_operation"

        raise ValueError(
            "No safe alternative strategy is available for this command."
        )
