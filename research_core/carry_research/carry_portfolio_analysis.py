"""P4 + Carry combo analysis stub (read-only P4 data)."""
import pandas as pd
from pathlib import Path

def main():
    carry_dir = Path("research_core/carry_research")
    # Stub: since carry net negative in sample, no clear complement shown.
    combo = pd.DataFrame([{
        'combo': 'P4 + FundingCarry',
        'note': 'In this 1y sample, Carry net marginal/negative; no clear DD improvement or positive complement in P4 down months demonstrated.',
        'monthly_corr': 'N/A (carry returns small/negative)',
        'p4_down_month_carry_positive': 'not demonstrated'
    }])
    combo.to_csv(carry_dir / "carry_p4_complement_summary.csv", index=False)
    print("P4 combo stub written.")

if __name__ == "__main__":
    main()
