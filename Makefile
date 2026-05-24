OUTPUT_DIR = output
PORT = 8080

.PHONY: serve clean

serve:
	mkdir -p $(OUTPUT_DIR)
	python3 pi_monitor.py --output $(OUTPUT_DIR)/index.html
	@echo "Serving at http://localhost:$(PORT)"
	python3 -m http.server $(PORT) --bind 0.0.0.0 --directory $(OUTPUT_DIR)

clean:
	rm -rf $(OUTPUT_DIR)
