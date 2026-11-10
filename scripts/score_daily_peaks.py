"""Score saved validation forecasts on daily peak error (Azm and Household 3)."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lebanon_energy.evaluation.peak_scores import main
if __name__ == '__main__':
    main()
