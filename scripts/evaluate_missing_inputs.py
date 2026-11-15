"""Score the served forecast when meter history is missing, with and without fallbacks."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lebanon_energy.evaluation.missing_inputs import main
if __name__ == '__main__':
    main()
