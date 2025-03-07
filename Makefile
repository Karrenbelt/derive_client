.PHONY: tests
tests:
	poetry run pytest tests -vv  --reruns 10 --reruns-delay 30

fmt:
	poetry run black tests derive examples
	poetry run isort tests derive examples

lint:
	poetry run flake8 tests derive examples

all: fmt lint tests

test-docs:
	echo making docs

release:
	$(eval current_version := $(shell poetry run tbump current-version))
	@echo "Current version is $(current_version)"
	$(eval new_version := $(shell python -c "import semver; print(semver.bump_patch('$(current_version)'))"))
	@echo "New version is $(new_version)"
	poetry run tbump $(new_version)

