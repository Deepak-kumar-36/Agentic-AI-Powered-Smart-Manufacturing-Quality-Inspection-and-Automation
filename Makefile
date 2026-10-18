.PHONY: test

test:
	python -m unittest discover -s tests -v
	@if command -v node >/dev/null 2>&1; then node --test tests/dashboard_analytics.test.cjs; else echo 'SKIP: node not installed; dashboard checks not run'; fi
