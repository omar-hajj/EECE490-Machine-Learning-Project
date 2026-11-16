"""One-shot test of the tuning procedure on Household 3's July (rehearses on June unless --open-test-set)."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lebanon_energy.evaluation.transfer_test import main
if __name__ == '__main__':
    main()
