from dataclasses import dataclass
from backtest_auditor.domain.enums import IssueSeverity


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    severity: IssueSeverity
    blocking: bool
    location: str | None = None


class InputValidationError(ValueError):
    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        if not issues:
            raise ValueError("InputValidationError requires at least one issue")

        self.issues = issues

        summary = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)

        super().__init__(summary)
