import os
os.environ.setdefault('MPLBACKEND', 'Agg')
os.environ.setdefault('GIT_PYTHON_REFRESH', 'quiet')
# Matplotlib's font cache must never target _MEIPASS or the install directory.
from app_paths import data_root
os.environ.setdefault('MPLCONFIGDIR', str(data_root() / 'cache' / 'matplotlib'))
