# make -C research/paper  -> regenerates numbers from research/results and builds the PDF
all: numbers figs tooldemo workshop
numbers:
	python3 scripts/make_numbers.py
figs:
	python3 scripts/make_figs.py
workshop:
	cd $@ && latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
tooldemo:
	cd $@ && latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
clean:
	cd tooldemo && latexmk -C
	cd workshop && latexmk -C
.PHONY: all numbers figs tooldemo workshop clean
