VENV     := .venv
PYTHON   := $(VENV)/bin/python
PIP      := $(VENV)/bin/pip
OUT      ?= ./drive_download
WORKERS  ?= 8
SPEED_MB ?= 256

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

$(VENV)/bin/python:
	python3 -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -r requirements.txt

.PHONY: venv
venv: $(VENV)/bin/python ## Create the venv and install dependencies

.PHONY: test
test: venv ## Run the offline mocked dry-run test (no credentials needed)
	$(PYTHON) tests/test_dryrun.py

.PHONY: dry-run
dry-run: venv ## Real --dry-run against your Drive (needs credentials.json/token.json)
	$(PYTHON) download_drive_data.py --dry-run -o $(OUT)

.PHONY: run
run: venv ## Pick a target drive, then download your Drive there
	@mount=$$(SPEED_MB=$(SPEED_MB) ./drives.sh pick) && \
		dest="$$mount/drive_download" && \
		echo "Downloading to $$dest" && \
		$(PYTHON) download_drive_data.py -o "$$dest" --workers $(WORKERS)

.PHONY: photos
photos: venv ## Pick a target drive, then download your Google Photos there
	@mount=$$(SPEED_MB=$(SPEED_MB) ./drives.sh pick) && \
		dest="$$mount/photos_download" && \
		echo "Downloading to $$dest" && \
		$(PYTHON) download_photos_data.py -o "$$dest" --workers $(WORKERS)

.PHONY: clean
clean: ## Remove the venv and Python caches
	rm -rf $(VENV) __pycache__ tests/__pycache__

.PHONY: storage
storage: ## Show free space and write speed per drive (writes a temp file; SPEED_MB=256)
	@SPEED_MB=$(SPEED_MB) ./drives.sh list
