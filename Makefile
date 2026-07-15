PYTHON ?= python3
.PHONY: smoke showcase-axi4 showcase-overview

smoke:
	$(PYTHON) -m unittest discover -s tests -v

showcase-axi4:
	$(PYTHON) showcase/demos/axi4/run.py

showcase-overview:
	$(PYTHON) showcase/materials/assets/overview/render_png.py
	$(PYTHON) -m protocol_model
