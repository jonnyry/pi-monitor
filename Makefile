OUTPUT_DIR = output
PORT = 8080

.PHONY: serve clean test test-unit test-integration help

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  serve            Generate the dashboard and serve it on http://localhost:$(PORT)"
	@echo "  clean            Remove the $(OUTPUT_DIR)/ output directory"
	@echo "  test             Run all tests (unit + integration)"
	@echo "  test-unit        Run unit tests only"
	@echo "  test-integration Run integration tests only"
	@echo "  help             Show this help message"

serve:
	mkdir -p $(OUTPUT_DIR)
	python3 pi_monitor.py --output $(OUTPUT_DIR)/index.html
	@echo "Serving at http://localhost:$(PORT)"
	python3 -m http.server $(PORT) --bind 0.0.0.0 --directory $(OUTPUT_DIR)

clean:
	rm -rf $(OUTPUT_DIR)

test:
	python3 -m pytest tests/ -v

test-unit:
	python3 -m pytest tests/test_unit.py -v

test-integration:
	python3 -m pytest tests/test_integration.py -v
