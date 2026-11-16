"""Tune the forecast and the sizing rule on pre-September folds (course chapter 6)."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lebanon_energy.models.tuning import main
if __name__ == '__main__':
    main()
