from engine.contracts.intent_result import IntentResult
from engine.contracts.alternative_result import AlternativeResult

from engine.alternatives.templates import ALTERNATIVE_TEMPLATES


class AlternativeGenerator:
    """
    Generates safer command alternatives from an IntentResult.
    """

    def generate(self, result: IntentResult) -> AlternativeResult:
        """
        Generate a safer alternative based on the semantic intent.
        """

        strategy = self._select_strategy(result)

        template = ALTERNATIVE_TEMPLATES[strategy]

        return AlternativeResult(
            original_command=result.command,
            candidate_command=template.example_command,
            intent=result.intent,
            strategy=template.name,
            explanation=template.description,
        )

    def _select_strategy(self, result: IntentResult) -> str:
        """
        Select the safest available strategy based on the
        semantic meaning of the command.
        """

        text = (
            result.command
            + " "
            + result.intent
            + " "
            + result.impact
            + " "
            + result.explanation
        ).lower()

        # File deletion
        if (
            "-delete" in text
            or "delete files" in text
            or "deletes files" in text
            or "deleting files" in text
        ):
            return "file_deletion"

        # Directory removal
        if (
            "rm -rf" in text
            or "remove directory" in text
            or "delete directory" in text
            or "deleting directory" in text
        ):
            return "directory_deletion"

        # Permission modification
        if (
            "chmod" in text
            or "permission" in text
            or "permissions" in text
        ):
            return "permission_change"

        # Disk operations
        if (
            "mkfs" in text
            or "format disk" in text
            or "raw device" in text
            or "disk operation" in text
        ):
            return "disk_operation"

        # No known safer strategy.
        raise ValueError(
            "No safe alternative strategy is available "
            "for this command."
        )