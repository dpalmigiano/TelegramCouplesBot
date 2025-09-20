.PHONY: setup run test seed fmt worker

setup:
pip install -r requirements.txt

run:
python -m couples_bot.app

worker:
python -m workers.reag_worker

test:
pytest

seed:
python scripts/bootstrap_db.py && python scripts/seed_thresholds.py

fmt:
@echo "no-op"
