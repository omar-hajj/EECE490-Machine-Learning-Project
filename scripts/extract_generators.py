"""Extract observed Azm generator capacities and draft the selection policy."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lebanon_energy.generator_capacity import main
if __name__ == '__main__':
    main()
