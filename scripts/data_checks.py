"""Reproduce the data checks recorded in DATA_PROVENANCE.md."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lebanon_energy.data.data_checks import main
if __name__ == '__main__':
    main()
