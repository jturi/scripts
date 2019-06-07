..update upgrade
```
sudo apt-get update && sudo apt-get upgrade -y
```
..install apt packages
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
https://bitbucket.org/account/user/your_username/ssh-keys/
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