# FusionMap — common tasks.  `make help` lists them.
PY ?= .venv/bin/python
PIP ?= .venv/bin/pip

.PHONY: help install web serve demo test lint data train benchmark docker screenshots

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

install: ## create .venv and install FusionMap (+ dev tools)
	python3 -m venv .venv && $(PIP) install -U pip && $(PIP) install -e ".[dev]"

web: ## build the React app into fusionmap/static
	cd web && npm ci && npm run build

serve: ## run the web app + API on http://localhost:8000
	$(PY) -m fusionmap.cli serve

demo: ## simulate a patient and run the whole pipeline from the CLI
	$(PY) -m fusionmap.cli demo --seed 7

test: ## run the test suite
	$(PY) -m pytest -q -p no:warnings

lint:
	$(PY) -m ruff check fusionmap tests training

data: ## generate training data from randomised phantoms (needs .[train])
	$(PY) -m training.make_data --kind vxm --n 200 --out training/data/vxm
	$(PY) -m training.make_data --kind enhancer --n 32 --out training/data/enhancer

train: ## train both networks on CPU and export ONNX into fusionmap/models
	$(PY) -m training.train_enhancer --iters 3000
	$(PY) -m training.train_voxelmorph --iters 12000

benchmark: ## validation table on held-out phantoms -> docs/benchmark.json
	$(PY) -m fusionmap.cli benchmark --cases 12 --out docs/benchmark.json

docker: ## FusionMap + Orthanc PACS
	docker compose up --build
