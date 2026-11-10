"""Write Azm's hourly generator power, running share and configuration (September excluded)."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lebanon_energy.generators.capacity import main_hourly
if __name__ == '__main__':
    main_hourly()
