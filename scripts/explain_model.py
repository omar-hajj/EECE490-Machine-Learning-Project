"""Explain the served Ridge model: contribution of each input, overall and at daily peaks."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lebanon_energy.models.explain import main
if __name__ == '__main__':
    main()
