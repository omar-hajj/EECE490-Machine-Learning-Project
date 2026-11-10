"""Re-download Azm's observed and day-ahead forecast weather from Open-Meteo."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lebanon_energy.data.azm_weather import main
if __name__ == '__main__':
    main()
