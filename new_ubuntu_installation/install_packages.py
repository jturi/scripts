
from __future__ import with_statement
import re
import os
import time
import subprocess
import logging
import getpass

logging.basicConfig(format='%(levelname)-6s %(asctime)s.%(msecs)03d  /%(filename)s:%(lineno)-4d %(message)s',
    datefmt='%d-%m-%y %H:%M:%S',
    level=logging.DEBUG)

log = logging.getLogger(__name__)
"""
Run script with: sudo python path_to_script/apt_install.py
Will create apt_lists_installed.txt in the same folder for check
"""


requested_ppas = """
#for-python
deadsnakes/ppa
#for-redshift-screen-color
dobey/redshift-daily
#for-python
gezakovacs/ppa
#for-git
git-core/ppa
#for-copyq
hluk/copyq
#for-libreoffice
libreoffice/ppa
#for-timeshift-backup-application
teejee2008/ppa
#for-firefox-mozilla
ubuntu-mozilla-security/ppa
#for-atom-IDE
webupd8team/atom
"""
# INSTALL
requested_pckgs = """
aptitude
arduino
atom
copyq
curl
debian-keyring
ffmpeg
filezilla
flatpak
git
gparted
gwenview
hardinfo
htop
hunspell-en-gb
i3lock
scrot
imagemagick
krusader
kde-baseapps-bin
krename
mate-terminal
mplayer
net-tools
nmap
openssh-server
psensor
python-dev
python-pip
python3-pip
python3.6
python3.6-dev
python3.7-minimal
python3-tk
python-tk
redshift
shutter
snapd
snapd-xdg-open
sshfs
sysstat
timeshift
tmux
trash-cli
unrar
unzip
vlc
browser-plugin-vlc
xclip
xdotool
#-----------------OPTIONAL-------------------
#acpi-call-dkms
#arp-scan
#autofs
#cifs-utils
#build-essential
#calibre
#chntpw
#cifs-utils
#gconf-editor
#gnome-disk-utility
#gnome-themes-standard
#gnome-tweak-tool
#google-chrome-stable
#inxi
#libappindicator1
#libnotify-bin
#libreoffice
#software-properties-common
#tlp
#tlp-rdw
#tp-smapi-dkms
"""

uninstall_pckgs = """
rabbitmq-server
thunderbird
unetbootin
wireshark
"""


def run_cmd(cmd):
    """ Runs bash commands with subprocess.call"""
    cmd_to_list = cmd.split(" ")
    ret_code = subprocess.call(cmd_to_list)
    return ret_code


def hello():
    log.info('prints test hello message: {}'.format(hello))


def get_apt_installed_pckgs():
    installed = []
    cmd = 'sudo apt list --installed'
    output_binary = subprocess.check_output(cmd, shell=True)
    decoded = output_binary.decode("ascii")

    target = open("apt_lists_installed.txt", "w+")
    target.write(decoded)

    source = open("apt_lists_installed.txt", "r+")

    for line in source:
        apt_pckg_name = re.findall(r'^[^\/]+', line)[0]
        installed.append(apt_pckg_name)
    return installed


def get_ppa_not_added():
    installed = []
    requested = requested_ppas.split("\n")
    cmd = 'cat /etc/apt/sources.list; for X in /etc/apt/sources.list.d/*; do echo; echo; echo "** $X:"; echo; cat $X; done'
    output_binary = subprocess.check_output(cmd, shell=True)
    decoded = output_binary.decode("ascii")

    target = open("ppa_lists_installed.txt", "w+")
    target.write(decoded)

    source = open("ppa_lists_installed.txt", "r+")

    for line in source:
        for req in requested:
            if str(req).startswith("#"):
                continue
            if req in line:
                installed.append(line)

    not_added = [ppa for ppa in requested if ppa not in installed and len(ppa) > 3]
    return not_added


def get_apt_not_installed_pckgs():
    not_installed = []
    installed = get_apt_installed_pckgs()
    requested_list = requested_pckgs.split("\n")
    for req_pckg_name in requested_list:
        if str(req_pckg_name).startswith("#"):
            continue
        if not req_pckg_name:
            continue
        if req_pckg_name not in installed:
            not_installed.append(req_pckg_name)
    log.info("Not installed list: {}".format(not_installed))
    return not_installed


def apt_install():
    run_cmd("sudo apt-get update")
    not_installed = get_apt_not_installed_pckgs()
    for pckg in not_installed:
        run_cmd("sudo apt-get install {} -y".format(pckg))
    log.info("Requested but not installed: {}".format(not_installed))
    log.info("Packages still not installed: {}".format(
        get_apt_not_installed_pckgs()))
    return not_installed


def apt_uninstall():
    requested_list = uninstall_pckgs.split("\n")
    for pckg in requested_list:
        if str(pckg).startswith("#"):
            log.info("SKIPPING: {}".format(pckg))
        else:
            log.info("REMOVING: {}".format(pckg))
            run_cmd("sudo apt-get remove {} -y".format(pckg))
    log.info("Requested list processed: {}".format(requested_list))
    return requested_list


def add_ppas():
    not_added = get_ppa_not_added()
    log.info('not_added: {}'.format(not_added))
    time.sleep(1)
    for ppa in get_ppa_not_added():
        if str(ppa).startswith("#"):
            continue
        cmd = "sudo add-apt-repository ppa:{ppa} -y".format(ppa=ppa)
        log.info('cmd: {}'.format(cmd))
        run_cmd(cmd)

    refreshed_ppa = get_ppa_not_added()
    log.info('Not added ppa-s: {}'.format(not_added))
    log.info('Refreshed ppa: {}'.format(refreshed_ppa))
    return refreshed_ppa


def update_upgrade():
    run_cmd("sudo apt-get update")
    run_cmd("sudo apt-get upgrade -y")


if __name__ == '__main__':
    log.info('apt_install.py started')
    update_upgrade()
    add_ppas()
    apt_install()
