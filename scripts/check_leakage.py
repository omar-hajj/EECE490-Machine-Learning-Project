"""Write the Azm feature table and prove no feature uses data from after the issue time."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lebanon_energy.evaluation.leakage import main
if __name__ == '__main__':
    main()
