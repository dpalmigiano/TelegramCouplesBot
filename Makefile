.PHONY: setup run test seed fmt

setup:
pip install -r requirements.txt

run:
python -m couples_bot.app

test:
pytest

seed:
python scripts/bootstrap_db.py && python scripts/seed_thresholds.py

fmt:
@echo "No formatting step configured"
