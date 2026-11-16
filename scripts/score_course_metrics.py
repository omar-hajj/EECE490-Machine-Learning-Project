"""Score the served model with the chapter 6 metrics (regression, classification, statistical tests)."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lebanon_energy.evaluation.course_metrics import main
if __name__ == '__main__':
    main()
