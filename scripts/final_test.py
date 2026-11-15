"""One-shot final test on September (rehearses on August unless --open-test-set is given)."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lebanon_energy.evaluation.final_test import main
if __name__ == '__main__':
    main()
