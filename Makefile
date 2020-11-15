.ONESHELL:
.PHONY: help
.DEFAULT_GOAL := help

RED  := $(shell tput -Txterm setaf 1)
GREEN  := $(shell tput -Txterm setaf 2)
YELLOW := $(shell tput -Txterm setaf 3)
MAGENTA := $(shell tput -Txterm setaf 5)
RESET  := $(shell tput -Txterm sgr0)
TARGET_MAX_CHAR_NUM := 23
NAMESPACE := `kubectl config view --minify --output 'jsonpath={..namespace}'`
##### EDIT THESE #####
PYTHON=python3.8
## VENVPATH=.<venv_name>: hidden folder for python environment, included in gitignore with: .*/
VENVPATH=.your_project_name_here
ACTIVATE_FOLDER=bin
#ACTIVATE_FOLDER=Scripts
##### EDIT THESE #####
VENVPYTHON=. $(VENVPATH)/$(ACTIVATE_FOLDER)/activate; python

.PHONY: help
help:
	@echo 'Usage:'
	@echo '  ${RED}make${RESET} ${MAGENTA}command${RESET}'
	@echo 'Commands:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-$(TARGET_MAX_CHAR_NUM)s$(RESET)$(GREEN)%s$(RESET)\n", $$1, $$2}'

guard-%: # Makes sure all required environment variables are set.
	@ if [ "${${*}}" = "" ]; then \
		echo '${RED}$* environment variable missing. Please set it with:${RESET}'; \
		echo '${YELLOW}export $*=value_here${RESET}'; \
		exit 1; \
	fi
  
  
kubectl:
	@if [ x "$(command -v kubectl)" ]; then \
	echo "${RED}kubectl binary not found, please use instructions in README file:${RESET}"; exit 1; fi

skaffold:
	@if [ x "$(command -v skaffold)" ]; then \
	echo "${RED}skaffold binary not found, please use instructions in README file:${RESET}"; exit 1; fi

.prompt-yesno:
	@exec 9<&0 0</dev/tty
	echo '${GREEN}$(message)${RESET}'
	echo '${GREEN}Auto Starting in 15 seconds.. [Y]:${RESET}'
	[[ -z $$FOUNDATION_NO_WAIT ]] && read -rs -t15 -n 1 yn;
	exec 0<&9 9<&-
	[[ -z $$yn ]] || [[ $$yn == [yY] ]] && echo Y >&2 || (echo N >&2 && exit 1)
  @#if make .prompt-yesno message="Do you want to continue y/n?" 2> /dev/null; then \

prepare-dev:  ## create virtual environment (local development)
	sudo add-apt-repository ppa:deadsnakes/ppa -y
	sudo apt-get update
	sudo apt-get -y install $(PYTHON) python3-pip
	$(PYTHON) -m pip install virtualenv

installchromedriver: ## Install selenium test chromedriver for linux
	wget -O /tmp/chromedriver.zip http://chromedriver.storage.googleapis.com/`curl -sS chromedriver.storage.googleapis.com/LATEST_RELEASE`/chromedriver_linux64.zip
	sudo unzip /tmp/chromedriver.zip chromedriver -d /usr/local/bin/

venv: $(VENVPATH)/$(ACTIVATE_FOLDER)/activate

act: venv ## activate virtual environment
	@echo "run: ${GREEN}. $(VENVPATH)/$(ACTIVATE_FOLDER)/activate${RESET}"

$(VENVPATH)/$(ACTIVATE_FOLDER)/activate: ./requirements.txt
	$(PYTHON) -V || make prepare-dev
	test -d $(VENVPATH) || $(PYTHON) -m virtualenv $(VENVPATH)
	$(VENVPYTHON) -m pip install -Ur ./requirements.txt
	@echo ">> venv activated"
	touch $(VENVPATH)/$(ACTIVATE_FOLDER)/activate

freeze:	venv
	$(VENVPYTHON) -m pip freeze

cleanpyc:
	find . | grep -E "(__pycache__|\.pyc)" | xargs rm -rf
