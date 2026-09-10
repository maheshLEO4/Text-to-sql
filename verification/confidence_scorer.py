import json
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

# Import data structures from earlier steps
from verification.hallucination_detector import BacktranslationVerificationResult
from verification.result_sanity_checker import SanityCheckResult
from verification.multi_query_validator import ConsensusValidationResult


class OverallConfidenceReport(BaseModel):
    composite_confidence_score: float = Field(
        ..., 
        description="Final aggregated confidence score between 0.0 and 1.0."
    )
    confidence_tier: str = Field(
        ..., 
        description="Qualitative rating: 'HIGH', 'MEDIUM', 'LOW', or 'CRITICAL_FAILURE'."
    )
    signal_breakdown: Dict[str, float] = Field(
        ..., 
        description="Individual weighted score contribution from each validation layer."
    )
    passed_all_layers: bool = Field(
        ..., 
        description="True if all critical checks passed without fatal flags."
    )
    warnings: list[str] = Field(
        default_factory=list, 
        description="Combined list of non-critical warnings across all layers."
    )
    critical_issues: list[str] = Field(
        default_factory=list, 
        description="Combined list of severe issues or hallucination warnings."
    )


class ConfidenceScoringEngine:
    """
    Combines hallucination, sanity, guardrail, and consensus verification signals
    into a unified confidence metric.
    """

    def __init__(
        self,
        weight_syntax: float = 0.20,
        weight_backtranslation: float = 0.35,
        weight_sanity: float = 0.25,
        weight_consensus: float = 0.20
    ):
        self.w_syntax = weight_syntax
        self.w_backtranslation = weight_backtranslation
        self.w_sanity = weight_sanity
        self.w_consensus = weight_consensus

    def calculate_confidence(
        self,
        is_syntax_valid: bool,
        backtranslation_res: BacktranslationVerificationResult,
        sanity_res: SanityCheckResult,
        consensus_res: Optional[ConsensusValidationResult] = None
    ) -> OverallConfidenceReport:
        """
        Computes composite confidence score and qualitative rating.
        """
        warnings = []
        critical_issues = []

        # 1. Syntax Score (0.0 or 1.0)
        syntax_score = 1.0 if is_syntax_valid else 0.0
        if not is_syntax_valid:
            critical_issues.append("Syntax Check Failed: Generated query contains invalid SQL syntax.")

        # 2. Backtranslation Alignment Score (0.0 to 1.0)
        backtrans_score = max(0.0, min(1.0, backtranslation_res.alignment_score))
        if not backtranslation_res.is_aligned:
            critical_issues.append(
                f"Backtranslation Alignment Divergence: Score {backtranslation_res.alignment_score:.2f}. "
                f"Reason: {backtranslation_res.alignment_reasoning}"
            )

        # 3. Sanity Check Score (0.0 or 1.0)
        sanity_score = 1.0 if sanity_res.is_sane else 0.2
        warnings.extend(sanity_res.warnings)
        critical_issues.extend(sanity_res.critical_errors)

        # 4. Consensus Score (0.0 to 1.0)
        if consensus_res:
            consensus_score = consensus_res.agreement_score
            if not consensus_res.is_consensus_reached:
                warnings.append(f"Consensus Variance: {consensus_res.variance_details}")
        else:
            # If multi-query consensus was not run, assign default 1.0 score and redistribute
            consensus_score = 1.0

        # Weighted calculation
        composite_score = round(
            (syntax_score * self.w_syntax) +
            (backtrans_score * self.w_backtranslation) +
            (sanity_score * self.w_sanity) +
            (consensus_score * self.w_consensus),
            3
        )

        # Categorize Confidence Tier
        if critical_issues or composite_score < 0.50:
            tier = "CRITICAL_FAILURE"
            passed_all = False
        elif composite_score >= 0.85:
            tier = "HIGH"
            passed_all = True
        elif composite_score >= 0.65:
            tier = "MEDIUM"
            passed_all = True
        else:
            tier = "LOW"
            passed_all = False

        return OverallConfidenceReport(
            composite_confidence_score=composite_score,
            confidence_tier=tier,
            signal_breakdown={
                "syntax_validity": syntax_score,
                "backtranslation_alignment": backtrans_score,
                "result_sanity": sanity_score,
                "multi_query_consensus": consensus_score
            },
            passed_all_layers=passed_all,
            warnings=warnings,
            critical_issues=critical_issues
        )


# -----------------------------------------------------------------------------
# Quick Standalone Test Driver
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    scorer = ConfidenceScoringEngine()

    # Mock inputs for test
    mock_bt_pass = BacktranslationVerificationResult(
        backtranslated_question="Show top 5 spending customers",
        alignment_score=1.0,
        alignment_reasoning="Matches intent perfectly.",
        is_aligned=True
    )

    mock_sanity_pass = SanityCheckResult(
        is_sane=True,
        passed_checks=["Non-empty", "Valid NULL bounds"],
        warnings=[],
        critical_errors=[],
        null_percentage_by_column={"customer_id": 0.0}
    )

    mock_consensus_pass = ConsensusValidationResult(
        is_consensus_reached=True,
        agreement_score=1.0,
        variant_1_sql="SELECT 1",
        variant_2_sql="SELECT 1",
        variance_details="Exact match"
    )

    print("--- Test 1: Perfect Signals (High Confidence) ---")
    report1 = scorer.calculate_confidence(
        is_syntax_valid=True,
        backtranslation_res=mock_bt_pass,
        sanity_res=mock_sanity_pass,
        consensus_res=mock_consensus_pass
    )
    print(json.dumps(report1.model_dump(), indent=2))