"""Run the planned XGBoost validation comparison."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lebanon_energy.boosting import main
if __name__ == "__main__":
    main()
