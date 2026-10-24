.PHONY: clean sdist pre-commit mkdocs

sdist: clean
	python3 -m build --sdist --wheel --outdir dist/ .

clean:
	rm -rf build dailycheckin.egg-info dist

pre-commit:
	pre-commit run --all-files
