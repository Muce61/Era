import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from research.trend_research_pipeline import main


if __name__ == "__main__":
    main()
