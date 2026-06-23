.PHONY: install uninstall start stop restart update status logs

PLAYBOOK_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
INVENTORY := $(PLAYBOOK_DIR)inventory.ini

install:
	ansible-playbook -i $(INVENTORY) $(PLAYBOOK_DIR)playbook.yml --tags install

uninstall:
	ansible-playbook -i $(INVENTORY) $(PLAYBOOK_DIR)playbook.yml --tags uninstall

start:
	ansible-playbook -i $(INVENTORY) $(PLAYBOOK_DIR)playbook.yml --tags start

stop:
	ansible-playbook -i $(INVENTORY) $(PLAYBOOK_DIR)playbook.yml --tags stop

restart:
	ansible-playbook -i $(INVENTORY) $(PLAYBOOK_DIR)playbook.yml --tags restart

update:
	ansible-playbook -i $(INVENTORY) $(PLAYBOOK_DIR)playbook.yml --tags update

status:
	ansible-playbook -i $(INVENTORY) $(PLAYBOOK_DIR)playbook.yml --tags status

logs:
	docker compose -f $(PLAYBOOK_DIR)compose.yaml logs -f --tail=100
