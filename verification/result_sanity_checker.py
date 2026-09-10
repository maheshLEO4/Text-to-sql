import pandas as pd
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class SanityCheckResult(BaseModel):
    is_sane: bool = Field(
        ..., 
        description="True if the query results pass all sanity rules without critical anomalies."
    )
    passed_checks: List[str] = Field(
        default_factory=list, 
        description="List of sanity check descriptions that passed."
    )
    warnings: List[str] = Field(
        default_factory=list, 
        description="List of warning messages for non-critical anomalies detected."
    )
    critical_errors: List[str] = Field(
        default_factory=list, 
        description="List of critical error messages flagging bad joins or severe data anomalies."
    )
    null_percentage_by_column: Dict[str, float] = Field(
        default_factory=dict, 
        description="Percentage of NULL/None values per column in the result dataset."
    )


class ResultSanityChecker:
    """
    Performs deterministic sanity and statistical checks on the pandas DataFrame
    produced by executing generated SQL against the database.
    """

    def __init__(self, max_null_threshold: float = 0.50):
        """
        :param max_null_threshold: Float between 0.0 and 1.0. If null ratio exceeds 
                                   this in any column, flag as a bad join/data anomaly.
        """
        self.max_null_threshold = max_null_threshold

    def check_results(
        self, 
        data: List[Dict[str, Any]], 
        numeric_bounds: Optional[Dict[str, Dict[str, float]]] = None
    ) -> SanityCheckResult:
        """
        Executes deterministic sanity rules over extracted database rows.
        
        :param data: Raw list of dict records returned by database execution sandbox.
        :param numeric_bounds: Optional dict specifying min/max allowed for specific columns.
                               Example: {"unit_price": {"min": 0.0}, "quantity": {"min": 1}}
        """
        passed_checks = []
        warnings = []
        critical_errors = []
        null_percentage_by_column = {}

        # ---------------------------------------------------------------------
        # Rule 1: Check for Empty Result Sets
        # ---------------------------------------------------------------------
        if not data:
            warnings.append("Result dataset is empty (0 rows returned). Query filters may be overly restrictive.")
            return SanityCheckResult(
                is_sane=True,  # Empty results are valid in SQL, but worth warning
                passed_checks=["Empty set evaluation"],
                warnings=warnings,
                critical_errors=[],
                null_percentage_by_column={}
            )

        passed_checks.append("Result set is non-empty")
        df = pd.DataFrame(data)

        # ---------------------------------------------------------------------
        # Rule 2: NULL / Missing Data Concentration
        # ---------------------------------------------------------------------
        total_rows = len(df)
        high_null_cols = []

        for col in df.columns:
            null_count = df[col].isnull().sum()
            null_pct = round(float(null_count / total_rows), 4)
            null_percentage_by_column[col] = null_pct

            if null_pct > self.max_null_threshold:
                high_null_cols.append(f"Column '{col}' is {null_pct * 100:.1f}% NULL")

        if high_null_cols:
            critical_errors.append(
                f"High NULL ratio detected. Might indicate bad JOIN or incorrect foreign key: {', '.join(high_null_cols)}"
            )
        else:
            passed_checks.append(f"NULL thresholds within acceptable bounds (<={self.max_null_threshold * 100:.0f}%)")

        # ---------------------------------------------------------------------
        # Rule 3: Numeric Bounds Check (e.g. negative prices, negative stock)
        # ---------------------------------------------------------------------
        if numeric_bounds:
            for col, bounds in numeric_bounds.items():
                if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
                    col_min = bounds.get("min")
                    col_max = bounds.get("max")

                    if col_min is not None and (df[col] < col_min).any():
                        critical_errors.append(
                            f"Numerical anomaly: Column '{col}' contains values below minimum threshold of {col_min}."
                        )
                    if col_max is not None and (df[col] > col_max).any():
                        critical_errors.append(
                            f"Numerical anomaly: Column '{col}' contains values above maximum threshold of {col_max}."
                        )

        # Default sanity checks for standard order/e-commerce monetary fields
        monetary_or_qty_cols = [c for c in df.columns if any(k in c.lower() for k in ["price", "quantity", "amount", "revenue", "freight"])]
        for col in monetary_or_qty_cols:
            if pd.api.types.is_numeric_dtype(df[col]):
                if (df[col] < 0).any():
                    warnings.append(f"Column '{col}' contains negative numbers. Ensure business logic permits negative values.")

        if not any("Numerical anomaly" in err for err in critical_errors):
            passed_checks.append("Numerical boundary parameters validated")

        # ---------------------------------------------------------------------
        # Rule 4: Suspicious Column Uniformity
        # ---------------------------------------------------------------------
        if total_rows > 10:
            for col in df.columns:
                unique_vals = df[col].nunique(dropna=True)
                if unique_vals == 1:
                    warnings.append(f"Column '{col}' has identical values across all {total_rows} rows.")

        is_sane = len(critical_errors) == 0

        return SanityCheckResult(
            is_sane=is_sane,
            passed_checks=passed_checks,
            warnings=warnings,
            critical_errors=critical_errors,
            null_percentage_by_column=null_percentage_by_column
        )

    def check_sanity(
        self,
        data: List[Dict[str, Any]],
        numeric_bounds: Optional[Dict[str, Dict[str, float]]] = None
    ) -> SanityCheckResult:
        """Compatibility wrapper used by the pipeline harness."""
        return self.check_results(data=data, numeric_bounds=numeric_bounds)


# -----------------------------------------------------------------------------
# Quick Standalone Test Driver
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    checker = ResultSanityChecker()

    print("--- Test 1: Clean Data ---")
    clean_data = [
        {"product_name": "Chai", "unit_price": 18.0, "quantity": 10},
        {"product_name": "Chang", "unit_price": 19.0, "quantity": 25},
        {"product_name": "Aniseed Syrup", "unit_price": 10.0, "quantity": 15}
    ]
    res1 = checker.check_results(clean_data)
    print(json.dumps(res1.model_dump(), indent=2))

    print("\n--- Test 2: Anomaly Data (Bad JOIN producing NULLs & negative prices) ---")
    anomalous_data = [
        {"product_name": "Chai", "customer_name": None, "unit_price": -15.0},
        {"product_name": "Chang", "customer_name": None, "unit_price": 20.0},
        {"product_name": "Aniseed Syrup", "customer_name": None, "unit_price": 12.0}
    ]
    res2 = checker.check_results(anomalous_data)
    print(json.dumps(res2.model_dump(), indent=2))