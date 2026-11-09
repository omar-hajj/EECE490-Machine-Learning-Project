"""Run the approved six-site location-only input experiment."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lebanon_energy.location_trial import main
if __name__ == '__main__':
    main()
