..update upgrade
```
sudo apt-get update && sudo apt-get upgrade -y
```

..install_first_packages
```
sudo apt-get install -y tmux htop git sshfs xclip xdotool unrar unzip trash-cli \
mc make python-pip python3-pip python3.7-minimal supervisor
```

..install apt packages bulk
```
python /home/jturi/repos/notes/scripts/ubuntu_new_install/apt_install.py
```
..password_asterisks ..passwd_asterisks ..sudo_timeout change password timeout
```
sudo visudo
#change this line to:
Defaults        env_reset, timestamp_timeout=360, pwfeedback
```
..GRUB switch on detailed boot screen
```
sudo atom /etc/default/grub
# GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"
GRUB_CMDLINE_LINUX_DEFAULT=""
```

..mate-terminal
```
sudo apt-get install mate-terminal -y
mate-terminal --geometry=139x36-0+0


Edit/Profile
General >> Monospace 14
General >> Disable Bell
Scrolling >> back 2048 lines
Color >> Background: #300A24 || Font White-grey

## autosuggestions zsh shell
echo $SHELL
https://sunlightmedia.org/bash-vs-zsh/
git clone https://github.com/zsh-users/zsh-autosuggestions ~/.zsh/zsh-autosuggestions
source ~/.zsh/zsh-autosuggestions/zsh-autosuggestions.zsh
```

..font-size
```
Set Font sizes to 14
```

..ssh-keys, change keys
```
https://bitbucket.org/account/user/jturi/ssh-keys/
### generate ssh key
ssh-keygen -b 4096
### copy ssh key to clipboard
cat ~/.ssh/id_rsa.pub | xclip -sel clip
```

..kde-plasma widgets
```
Resource Monior Graph
Show CPU Momitor
Show RAM Monitor
SysMon plasmoid
Thermal Monitor
Simple System Monitor

Task Switcher --> Select Compact
```

..ssh_git
```
install git htop xclip xdotool atom

git config --global user.email "josephturi@gmail.com"
git config --global user.name "jturi"
### list ssh keys
ls ~/.ssh
### show ssh key
ssh-keygen -lf
### generate ssh key
ssh-keygen -b 4096
### copy ssh key to clipboard
cat ~/.ssh/id_rsa.pub | xclip -sel clip
```

..copy_to_clipboard
```
sudo apt-get install xclip -y
cat file_path_here | xclip -sel clip
```


..venv_wrapper
```
sudo apt install python3.7-minimal
wget https://bootstrap.pypa.io/get-pip.py
sudo python3.7 get-pip.py
pip -V
sudo pip install virtualenv virtualenvwrapper
mkdir ~/venvs
nano ~/.bashrc
---
## Virtualenv

# export WORKON_HOME=$HOME/.venvs
# export VIRTUALENVWRAPPER_PYTHON=/usr/bin/python3
# source /usr/local/bin/virtualenvwrapper.sh
---
source ~/.bashrc
mkvirtualenv bfo
workon bfo
```