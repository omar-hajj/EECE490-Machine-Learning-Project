"""Run the daily rolling-origin check (Azm net load by default; --site household_3 for the transfer check)."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lebanon_energy.models.walk_forward import main
if __name__ == '__main__':
    main()
